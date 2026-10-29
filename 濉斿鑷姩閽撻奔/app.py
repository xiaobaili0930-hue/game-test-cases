"""本地控制台：环境检测 / 参数 / 开始停止 / 实时日志（Windows / macOS）。stdlib 实现，无额外依赖。
启动：macOS   .venv/bin/python app.py
      Windows .venv\\Scripts\\python.exe app.py
      → http://127.0.0.1:8766   （可用 --port 换端口）
"""
import ctypes
import json
import os
import platform
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8766
PYTHON = sys.executable

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# ---------- 环境 / 权限检测（Windows 与 macOS 口径分开） ----------
def _cg():
    return ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")


def screen_capture_ok():
    """真抓一帧判断截屏能不能用。
    macOS：先走 CoreGraphics 预检（需要「屏幕录制」授权，否则抓到的是桌面壁纸）；
    Windows：没有同类授权机制，能抓到一帧即通过。"""
    if IS_MAC:
        try:
            f = _cg().CGPreflightScreenCaptureAccess
            f.restype = ctypes.c_bool
            return bool(f())
        except Exception:
            return None
    try:
        import mss
        with mss.mss() as s:
            mon = s.monitors[1] if len(s.monitors) > 1 else s.monitors[0]
            shot = s.grab(mon)
        return shot.width > 0 and shot.height > 0
    except Exception:
        return None


def accessibility_ok():
    """辅助功能授权：macOS 用 System Events 控窗 + 合成点击所必需；Windows 没有这个机制，
    pyautogui 直接可用，因此恒为 True（下面的截屏自检已经覆盖了真正会拦路的环节）。"""
    if not IS_MAC:
        return True
    try:
        lib = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        f = lib.AXIsProcessTrusted
        f.restype = ctypes.c_bool
        return bool(f())
    except Exception:
        return None


def request_perm(which):
    """打开系统授权面板（只有 macOS 需要）。"""
    if not IS_MAC:
        return
    if which == "screen":
        try:
            f = _cg().CGRequestScreenCaptureAccess
            f.restype = ctypes.c_bool
            f()
        except Exception:
            pass
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"])
    else:
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])


def host_app():
    """当前控制台跑在哪个宿主里（macOS 上用来提示「权限要授给谁」）。"""
    if IS_WIN:
        if os.environ.get("WT_SESSION"):
            return "Windows Terminal"
        return f"Windows 控制台（{Path(sys.executable).name}）"
    tp = os.environ.get("TERM_PROGRAM", "")
    return {"Apple_Terminal": "终端 Terminal", "iTerm.app": "iTerm", "vscode": "VS Code / Cursor"}.get(
        tp, tp or "未知（看启动它的应用）")


def deps_ok():
    """只检查当前平台真正需要的包：Windows 不需要、也装不上 pyobjc/Quartz。"""
    need = ["mss", "cv2", "pyautogui", "numpy"]
    if IS_MAC:
        need.append("Quartz")
    missing = []
    for m in need:
        try:
            __import__(m)
        except Exception:
            missing.append(m)
    return missing


def find_window():
    try:
        sys.path.insert(0, str(HERE))
        from screen import locate_window
        cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
        return locate_window(cfg["window_title"]), cfg
    except Exception as e:
        return None, {"error": str(e)}


def displays():
    """显示器列表（跨平台，用 mss 枚举；macOS 上就是 Quartz 那批）。"""
    try:
        import mss
        with mss.mss() as s:
            mons = s.monitors
        return [{"x": m["left"], "y": m["top"], "w": m["width"], "h": m["height"]} for m in mons[1:]]
    except Exception:
        return []


def dpi_scale():
    """Windows 的显示缩放百分比（96 DPI = 100%）；非 Windows 返回 None。"""
    if not IS_WIN:
        return None
    try:
        return round(ctypes.windll.user32.GetDpiForSystem() / 96 * 100)
    except Exception:
        return None


def run_check():
    win, cfg = find_window()
    return {
        "python": platform.python_version(),
        "system": platform.system(),
        "host_app": host_app(),
        "deps_missing": deps_ok(),
        "screen_capture": screen_capture_ok(),
        "accessibility": accessibility_ok(),
        "config_ok": (HERE / "config.json").exists(),
        "window": None if win is None else {"x": win[0], "y": win[1], "w": win[2], "h": win[3]},
        "window_title": cfg.get("window_title"),
        "window_size_ref": cfg.get("window_size"),
        "displays": displays(),
        "dpi_scale": dpi_scale(),
    }


# ---------- 子进程管理 ----------
CREATE_NEW_PROCESS_GROUP = 0x00000200


class Runner:
    def __init__(self):
        self.proc = None
        self.lines = deque(maxlen=400)
        self.started = None
        self.rounds = self.hits = 0
        self.state = "-"
        self.lock = threading.Lock()

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, p):
        if self.running():
            return False, "已经在跑"
        args = [PYTHON, "-u", str(HERE / "fish.py")]
        if int(p.get("rounds", 0)) > 0:
            args += ["--rounds", str(int(p["rounds"]))]
        if p.get("restore_cursor"):
            args.append("--restore-cursor")
        if p.get("reset_window"):
            args.append("--reset-window")
        if p.get("dry"):
            args.append("--dry")
        if p.get("lead_ms"):
            args += ["--lead-ms", str(float(p["lead_ms"]))]
        self.lines.clear(); self.rounds = self.hits = 0; self.state = "启动中"
        self.started = time.time()
        # 子进程强制 UTF-8 输出：Windows 控制台的默认代码页编码不了「⚠」这类字符，会直接报错
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(args, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1, encoding="utf-8", errors="replace",
                                     env=env, creationflags=(CREATE_NEW_PROCESS_GROUP if IS_WIN else 0))
        threading.Thread(target=self._pump, daemon=True).start()
        return True, " ".join(args[2:])

    def _pump(self):
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            with self.lock:
                self.lines.append(line)
                if "轮结束，累计命中" in line:
                    try:
                        seg = line.split("第 ")[1]
                        self.rounds = int(seg.split(" 轮")[0]); self.hits = int(line.rsplit("累计命中 ", 1)[1])
                    except Exception:
                        pass
                if " -> " in line:
                    self.state = line.split(" -> ")[1].split()[0]
        with self.lock:
            self.state = "已停止"

    def stop(self):
        if not self.running():
            return False
        try:
            if IS_WIN:
                # Windows 不支持给子进程发 SIGINT，用 Ctrl+Break（子进程要建在独立进程组里）
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.proc.send_signal(signal.SIGINT)
        except Exception:
            self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        return True

    def status(self):
        with self.lock:
            return {"running": self.running(), "state": self.state, "rounds": self.rounds, "hits": self.hits,
                    "elapsed": 0 if not self.started else int(time.time() - self.started),
                    "lines": list(self.lines)[-150:]}

RUN = Runner()

# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            b = (HERE / "ui" / "index.html").read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        elif self.path == "/api/check":
            self._json(run_check())
        elif self.path == "/api/status":
            self._json(RUN.status())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/start":
            ok, msg = RUN.start(body); self._json({"ok": ok, "msg": msg})
        elif self.path == "/api/stop":
            self._json({"ok": RUN.stop()})
        elif self.path == "/api/request_perm":
            request_perm(body.get("which")); self._json({"ok": True})
        elif self.path == "/api/reset_window":
            from screen import reset_window
            cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
            ok, msg = reset_window(cfg["window_title"], *cfg["window_ref"], *cfg["window_size"])
            self._json({"ok": ok, "msg": msg})
        else:
            self._json({"error": "not found"}, 404)


def _port():
    if "--port" in sys.argv:
        try:
            return int(sys.argv[sys.argv.index("--port") + 1])
        except Exception:
            pass
    return PORT


def main():
    port = _port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}"
    print("控制台:", url, "  Ctrl+C 退出")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        RUN.stop()


if __name__ == "__main__":
    main()
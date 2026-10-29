"""本地控制台：环境检测 / 参数 / 开始停止 / 实时日志。stdlib 实现，无额外依赖。
启动：.venv/bin/python app.py  → http://127.0.0.1:8766
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

# ---------- 权限检测（对当前进程；fish.py 子进程继承同一个「责任应用」，结论一致） ----------
def _cg():
    return ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")

def _ax():
    return ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")

def screen_capture_ok():
    try:
        f = _cg().CGPreflightScreenCaptureAccess; f.restype = ctypes.c_bool
        return bool(f())
    except Exception:
        return None

def accessibility_ok():
    try:
        f = _ax().AXIsProcessTrusted; f.restype = ctypes.c_bool
        return bool(f())
    except Exception:
        return None

def request_perm(which):
    if which == "screen":
        try:
            f = _cg().CGRequestScreenCaptureAccess; f.restype = ctypes.c_bool; f()
        except Exception:
            pass
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"])
    else:
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])

def host_app():
    tp = os.environ.get("TERM_PROGRAM", "")
    return {"Apple_Terminal": "终端 Terminal", "iTerm.app": "iTerm", "vscode": "VS Code / Cursor"}.get(tp, tp or "未知（看启动它的应用）")

def deps_ok():
    missing = []
    for m in ("mss", "cv2", "pyautogui", "Quartz", "numpy"):
        try:
            __import__(m)
        except Exception:
            missing.append(m)
    return missing

def find_window():
    try:
        sys.path.insert(0, str(HERE))
        from screen import locate_window
        cfg = json.loads((HERE / "config.json").read_text())
        return locate_window(cfg["window_title"]), cfg
    except Exception as e:
        return None, {"error": str(e)}

def displays():
    try:
        import Quartz
        n = Quartz.CGGetActiveDisplayList(8, None, None)[1]
        out = []
        for d in n:
            b = Quartz.CGDisplayBounds(d)
            out.append({"x": int(b.origin.x), "y": int(b.origin.y), "w": int(b.size.width), "h": int(b.size.height),
                        "retina": Quartz.CGDisplayPixelsWide(d) > b.size.width})
        return out
    except Exception:
        return []

def run_check():
    win, cfg = find_window()
    return {
        "python": platform.python_version(),
        "host_app": host_app(),
        "deps_missing": deps_ok(),
        "screen_capture": screen_capture_ok(),
        "accessibility": accessibility_ok(),
        "config_ok": (HERE / "config.json").exists(),
        "window": None if win is None else {"x": win[0], "y": win[1], "w": win[2], "h": win[3]},
        "window_title": cfg.get("window_title"),
        "window_size_ref": cfg.get("window_size"),
        "displays": displays(),
    }

# ---------- 子进程管理 ----------
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
        self.proc = subprocess.Popen(args, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1)
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
        self.proc.send_signal(signal.SIGINT)
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
            cfg = json.loads((HERE / "config.json").read_text())
            ok, msg = reset_window(cfg["window_title"], *cfg["window_ref"], *cfg["window_size"])
            self._json({"ok": ok, "msg": msg})
        else:
            self._json({"error": "not found"}, 404)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://127.0.0.1:{PORT}"
    print("控制台:", url, "  Ctrl+C 退出")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        RUN.stop()


if __name__ == "__main__":
    main()

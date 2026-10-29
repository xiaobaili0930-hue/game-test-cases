"""屏幕抓取 + 窗口定位 + 鼠标点击的统一封装（Windows / macOS）。

坐标口径：屏幕物理像素。Windows 下导入本模块即开启 per-monitor DPI awareness，
让 GetWindowRect / mss 抓屏 / pyautogui 点击三者坐标系统一（100% 缩放下等于逻辑点）；
窗口矩形一律返回 DWM 可视矩形（不含 Win10+ 的隐形边框），与肉眼所见、与校准量法一致。
"""
import ctypes
import random
import subprocess
import sys
import time

import cv2
import mss
import numpy as np
import pyautogui

pyautogui.FAILSAFE = True      # 鼠标甩到左上角 = 紧急停止
pyautogui.PAUSE = 0            # 关掉 pyautogui 每次操作后的默认 0.1s 睡眠

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# 窗口归属关键词：微信 Mac / Windows / 安卓模拟器（标题重名时用来挑对窗口）
OWNER_HINT = ("微信", "wechat", "weixin", "mumu")


# ---------------- Windows：窗口定位 / 复位 ----------------
if IS_WIN:
    _u32 = ctypes.windll.user32
    _k32 = ctypes.windll.kernel32
    try:
        _dwm = ctypes.windll.dwmapi
    except Exception:
        _dwm = None

    _DWMWA_EXTENDED_FRAME_BOUNDS = 9
    _SW_RESTORE = 9
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _dpi_on = False

    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    def _dpi_aware():
        """per-monitor DPI aware（幂等）。不开启的话 GetWindowRect 会被系统按虚拟化坐标返回，
        与 mss/pyautogui 的物理像素对不上，点击就会整体偏移。"""
        global _dpi_on
        if _dpi_on:
            return True
        for fn in (lambda: _u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)),
                   lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),
                   lambda: _u32.SetProcessDPIAware()):
            try:
                fn()
                _dpi_on = True
                return True
            except Exception:
                continue
        return False

    _dpi_aware()
    _u32.MoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_bool]
    _u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _u32.SetForegroundWindow.argtypes = [ctypes.c_void_p]

    def _proc_name(pid):
        h = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            n = ctypes.c_ulong(512)
            if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return buf.value.rsplit("\\", 1)[-1]
        finally:
            _k32.CloseHandle(h)
        return ""

    def _visible_rect(hwnd, frame):
        """DWM 可视矩形（去掉 Win10+ 的隐形边框）；拿不到就退回 GetWindowRect 的结果。"""
        if _dwm is not None:
            vr = _RECT()
            if not _dwm.DwmGetWindowAttribute(ctypes.c_void_p(hwnd),
                                              _DWMWA_EXTENDED_FRAME_BOUNDS,
                                              ctypes.byref(vr), ctypes.sizeof(vr)):
                return (vr.left, vr.top, vr.right - vr.left, vr.bottom - vr.top)
        return frame

    def _list_windows():
        """枚举可见顶层窗口：标题 / 归属进程 / 可视矩形 / 边框矩形。"""
        out = []
        ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        def _cb(hwnd, _lparam):
            if not _u32.IsWindowVisible(hwnd):
                return 1
            n = _u32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return 1
            buf = ctypes.create_unicode_buffer(n + 1)
            _u32.GetWindowTextW(hwnd, buf, n + 1)
            fr = _RECT()
            if not _u32.GetWindowRect(hwnd, ctypes.byref(fr)):
                return 1
            frame = (fr.left, fr.top, fr.right - fr.left, fr.bottom - fr.top)
            pid = ctypes.c_ulong(0)
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append({"hwnd": int(hwnd), "title": buf.value, "frame": frame,
                        "visible": _visible_rect(hwnd, frame), "proc": _proc_name(pid.value)})
            return 1

        _u32.EnumWindows(ENUMPROC(_cb), 0)
        return out

    def _find_hwnd(title, owner_hint=OWNER_HINT):
        cands = [x for x in _list_windows() if x["title"] == title]
        if not cands:
            return None

        def hinted(x):
            blob = (x["proc"] + " " + x["title"]).lower()
            return any(h.lower() in blob for h in owner_hint)

        return next((x for x in cands if hinted(x)), cands[0])


class Screen:
    """截屏封装。坐标一律用屏幕物理像素（Windows 100% 缩放下 = 逻辑点）；
    Retina 屏 mss 抓到的是物理像素，grab() 会自动缩回请求尺寸，上层不用关心。"""

    def __init__(self, monitor_index=1):
        self._sct = mss.MSS()
        mons = self._sct.monitors
        if len(mons) <= 1 or mons[0]["width"] == 0:
            why = ("终端没有「屏幕录制」权限（系统设置→隐私与安全性→屏幕录制 勾选你的终端）"
                   if IS_MAC else "桌面被锁定，或远程会话/显卡驱动异常")
            raise SystemExit(f"抓不到显示器：{why}")
        if monitor_index >= len(mons):
            raise SystemExit(f"monitor={monitor_index} 不存在，当前显示器: {mons[1:]}")
        self.mon = mons[monitor_index]          # 仅 grab_full/校准连拍用
        probe = self._sct.grab(self.mon)
        self.scale = probe.width / self.mon["width"]   # Retina 倍率；Windows 恒为 1.0

    def grab(self, roi):
        """roi=(x,y,w,h) 屏幕物理像素 → BGR ndarray，尺寸恒为 (h, w)。"""
        x, y, w, h = roi
        img = np.asarray(self._sct.grab({"left": x, "top": y, "width": w, "height": h}))
        img = np.ascontiguousarray(img[:, :, :3])
        if img.shape[1] != w or img.shape[0] != h:        # Retina：缩回请求尺寸
            img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
        return img

    def grab_full(self):
        """整块显示器（物理像素，校准连拍用）。"""
        img = np.asarray(self._sct.grab(self.mon))
        return np.ascontiguousarray(img[:, :, :3])

    def px_to_pt(self, px):
        return px / self.scale


def click(x, y, jitter=3, hold_ms=(30, 70), restore=False):
    """带随机抖动的点击：位置 ±jitter 像素，按下时长随机，避免机械同点同秒。
    restore=True 时点完把光标移回原位（借用光标约 50ms，让用户能继续用鼠标干别的）。"""
    jx = x + random.randint(-jitter, jitter)
    jy = y + random.randint(-jitter, jitter)
    orig = pyautogui.position() if restore else None
    pyautogui.moveTo(jx, jy)
    pyautogui.mouseDown()
    time.sleep(random.uniform(*hold_ms) / 1000)
    pyautogui.mouseUp()
    if orig is not None:
        pyautogui.moveTo(orig.x, orig.y)


def locate_window(title, owner_hint=OWNER_HINT):
    """按窗口标题找窗口，返回 (x, y, w, h) 屏幕物理像素；找不到返回 None。"""
    if IS_WIN:
        x = _find_hwnd(title, owner_hint)
        return None if x is None else x["visible"]
    import Quartz
    wl = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly,
                                           Quartz.kCGNullWindowID)
    for w in wl:
        if (w.get("kCGWindowName") or "") == title and \
           any(h in (w.get("kCGWindowOwnerName") or "") for h in owner_hint):
            b = w["kCGWindowBounds"]
            return int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"])
    return None


def reset_window(title, x, y, w, h):
    """把窗口挪到 (x,y) 并设成 w×h（Windows：MoveWindow+置前；macOS：System Events）。
    (x,y,w,h) 指可视矩形（屏幕物理像素）。返回 (ok, msg)。"""
    if IS_WIN:
        t = _find_hwnd(title)
        if t is None:
            return False, "notfound"
        fr, vr = t["frame"], t["visible"]
        # frame/visible 都是 (x, y, 宽, 高)；MoveWindow 按「边框矩形」设，先按可视矩形反推
        dx, dy = vr[0] - fr[0], vr[1] - fr[1]
        dw, dh = fr[2] - vr[2], fr[3] - vr[3]
        hwnd = ctypes.c_void_p(t["hwnd"])
        _u32.ShowWindow(hwnd, _SW_RESTORE)
        if not _u32.MoveWindow(hwnd, x - dx, y - dy, w + dw, h + dh, True):
            return False, "MoveWindow 失败"
        _u32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        # 隐形边框、最小尺寸限制等原因会让一次 MoveWindow 差几个像素，按实测可视矩形校正（最多两轮）
        tgt = (x, y, w, h)
        for _ in range(2):
            now = _find_hwnd(title)
            if now is None or max(abs(v - t) for v, t in zip(now["visible"], tgt)) <= 2:
                break
            v, f = now["visible"], now["frame"]
            if not _u32.MoveWindow(hwnd,
                                   f[0] + (x - v[0]), f[1] + (y - v[1]),
                                   f[2] + (w - v[2]), f[3] + (h - v[3]), True):
                return False, "MoveWindow 校正失败"
            time.sleep(0.3)
        now = _find_hwnd(title)
        if now is None:
            return True, "ok"
        v = now["visible"]
        return True, f"ok {v[2]}x{v[3]} @({v[0]},{v[1]})"
    script = f"""
tell application "System Events"
    repeat with pname in {{"微信", "WeChat"}}
        if exists process pname then
            tell process pname
                repeat with win in windows
                    if name of win is "{title}" then
                        set position of win to {{{x}, {y}}}
                        set size of win to {{{w}, {h}}}
                        perform action "AXRaise" of win
                        return "ok"
                    end if
                end repeat
            end tell
        end if
    end repeat
    return "notfound"
end tell"""
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    out = (r.stdout or r.stderr).strip()
    return out == "ok", out
"""屏幕抓取 + 鼠标点击的统一封装（macOS）。

坐标全部用「逻辑点」（pyautogui 口径）；mss 抓到的是物理像素，内部按 scale 换算。
"""
import random
import time

import cv2
import mss
import numpy as np
import pyautogui

pyautogui.FAILSAFE = True      # 鼠标甩到左上角 = 紧急停止
pyautogui.PAUSE = 0            # 关掉 pyautogui 每次操作后的默认 0.1s 睡眠


class Screen:
    """截屏封装。坐标一律用屏幕全局逻辑点（和 Quartz 窗口坐标、pyautogui 同一口径）。
    Retina 屏 mss 抓到的是物理像素，grab() 会自动缩回逻辑尺寸，上层不用关心。"""

    def __init__(self, monitor_index=1):
        self._sct = mss.MSS()
        mons = self._sct.monitors
        if len(mons) <= 1 or mons[0]["width"] == 0:
            raise SystemExit("抓不到显示器：屏幕锁定/休眠中，或终端没有「屏幕录制」权限"
                             "（系统设置→隐私与安全性→屏幕录制 勾选你的终端）")
        if monitor_index >= len(mons):
            raise SystemExit(f"monitor={monitor_index} 不存在，当前显示器: {mons[1:]}")
        self.mon = mons[monitor_index]          # 仅 grab_full/校准连拍用
        probe = self._sct.grab(self.mon)
        self.scale = probe.width / self.mon["width"]   # 该显示器 Retina 倍率

    def grab(self, roi):
        """roi=(x,y,w,h) 全局逻辑点 → BGR ndarray，尺寸恒为 (h, w)。"""
        x, y, w, h = roi
        img = np.asarray(self._sct.grab({"left": x, "top": y, "width": w, "height": h}))
        img = np.ascontiguousarray(img[:, :, :3])
        if img.shape[1] != w or img.shape[0] != h:        # Retina：缩回逻辑尺寸
            img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
        return img

    def grab_full(self):
        """整块显示器（物理像素，校准连拍用）。"""
        img = np.asarray(self._sct.grab(self.mon))
        return np.ascontiguousarray(img[:, :, :3])

    def px_to_pt(self, px):
        return px / self.scale


def click(x, y, jitter=3, hold_ms=(30, 70), restore=False):
    """带随机抖动的点击：位置 ±jitter 点，按下时长随机，避免机械同点同秒。
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


def locate_window(title, owner_hint=("微信", "WeChat")):
    """按窗口标题在屏幕上找窗口，返回 (x, y, w, h) 逻辑点；找不到返回 None。"""
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
    """用 System Events 把窗口挪到 (x,y) 并设成 w×h（需辅助功能权限）。返回是否成功。"""
    import subprocess
    script = f'''
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
end tell'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    out = (r.stdout or r.stderr).strip()
    return out == "ok", out

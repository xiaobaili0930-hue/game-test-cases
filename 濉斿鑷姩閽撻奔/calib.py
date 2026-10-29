"""校准工具：截一张钓鱼小游戏的图，框出轨道、取滑块/能量条颜色、标钓鱼按钮，写 config.json。

用法：
  python calib.py            # 5 秒倒计时后截屏（请切到游戏窗口，最好正处在小游戏中）
  python calib.py --snap     # 只截屏存到 debug/snap.png，不进交互
  python calib.py --img debug/snap.png   # 用已有截图校准

交互窗口按键：
  先拖一个矩形框住「滑块来回飘的整条轨道」，回车确认
  然后在图上：
    s = 对准滑块按 s 取色（可多按几次，不同位置）
    b = 对准能量条按 b 取色（可多按几次）
    f = 对准「钓鱼」按钮按 f
    t = 对准撞击时要点的位置按 t（不设则默认轨道中心）
    q = 保存退出
"""
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from screen import Screen  # noqa: E402

HERE = Path(__file__).parent
CFG = HERE / "config.json"
DEFAULT_TOL = (8, 50, 50)   # HSV 容差


def hsv_patch(img_bgr, x, y, r=3):
    patch = img_bgr[max(0, y - r): y + r + 1, max(0, x - r): x + r + 1]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    return np.median(hsv, axis=0).astype(int).tolist()


def hsv_range(samples, tol=DEFAULT_TOL):
    arr = np.array(samples)
    lo = np.clip(arr.min(axis=0) - tol, 0, [179, 255, 255])
    hi = np.clip(arr.max(axis=0) + tol, 0, [179, 255, 255])
    return [lo.tolist(), hi.tolist()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap", action="store_true")
    ap.add_argument("--img")
    ap.add_argument("--monitor", type=int, default=1)
    ap.add_argument("--delay", type=int, default=5)
    ap.add_argument("--burst", type=float, default=0, help="连拍秒数：每 --interval 秒截一张到 debug/burst/，不进交互")
    ap.add_argument("--interval", type=float, default=0.25)
    a = ap.parse_args()

    scr = Screen(a.monitor)
    if a.burst:
        out = HERE / "debug" / "burst"; out.mkdir(parents=True, exist_ok=True)
        for f in out.glob("*.*"): f.unlink()
        t0 = time.time(); n = 0
        while time.time() - t0 < a.burst:
            cv2.imwrite(str(out / f"{n:04d}.jpg"), scr.grab_full(), [cv2.IMWRITE_JPEG_QUALITY, 95]); n += 1
            time.sleep(a.interval)
        print(f"连拍 {n} 张 → debug/burst/")
        return
    if a.img:
        full = cv2.imread(a.img)
    else:
        for i in range(a.delay, 0, -1):
            print(f"{i}s 后截屏，请切到游戏窗口…", flush=True)
            time.sleep(1)
        full = scr.grab_full()
        (HERE / "debug").mkdir(exist_ok=True)
        name = time.strftime("snap_%H%M%S.png")
        cv2.imwrite(str(HERE / "debug" / name), full)
        cv2.imwrite(str(HERE / "debug" / "snap.png"), full)
        print(f"截图已存 debug/{name}（debug/snap.png 为最新一张）")
    if a.snap:
        return

    # 显示缩放：物理像素 → 窗口
    H, W = full.shape[:2]
    d = min(1.0, 1400 / W)
    disp = cv2.resize(full, None, fx=d, fy=d)

    cfg = json.loads(CFG.read_text(encoding="utf-8")) if CFG.exists() else {}
    cfg.setdefault("monitor", a.monitor)

    print("第一步：拖矩形框住滑块轨道，回车确认")
    x, y, w, h = cv2.selectROI("ROI", disp, showCrosshair=False)
    cv2.destroyWindow("ROI")
    if w == 0:
        print("没框 ROI，退出")
        return
    px = lambda v: int(v / d)            # 窗口 → 物理像素
    pt = lambda v: int(v / d / scr.scale)  # 窗口 → 逻辑点
    cfg["roi"] = [pt(x), pt(y), pt(w), pt(h)]
    cfg["axis"] = "x" if w >= h else "y"
    print("ROI(逻辑点)=", cfg["roi"], "方向=", cfg["axis"])

    state = {"pos": (0, 0), "slider": [], "bar": []}

    def on_mouse(ev, mx, my, flags, _):
        state["pos"] = (mx, my)

    win = "calib  (s=滑块 b=能量条 f=钓鱼按钮 t=点击位 q=保存)"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)
    while True:
        canvas = disp.copy()
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 255, 0), 1)
        mx, my = state["pos"]
        hsv = hsv_patch(full, px(mx), px(my))
        cv2.putText(canvas, f"HSV={hsv} slider={len(state['slider'])} bar={len(state['bar'])}",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.imshow(win, canvas)
        k = cv2.waitKey(30) & 0xFF
        if k == ord("s"):
            state["slider"].append(hsv); print("滑块取色", hsv)
        elif k == ord("b"):
            state["bar"].append(hsv); print("能量条取色", hsv)
        elif k == ord("f"):
            cfg["fish_button"] = [pt(mx), pt(my)]; print("钓鱼按钮", cfg["fish_button"])
        elif k == ord("t"):
            cfg["click_point"] = [pt(mx), pt(my)]; print("点击位", cfg["click_point"])
        elif k == ord("q") or k == 27:
            break
    cv2.destroyAllWindows()

    if state["slider"]:
        cfg["slider_hsv"] = hsv_range(state["slider"])
    if state["bar"]:
        cfg["bar_hsv"] = hsv_range(state["bar"])
    cfg.setdefault("click_point", [cfg["roi"][0] + cfg["roi"][2] // 2,
                                   cfg["roi"][1] + cfg["roi"][3] // 2])
    cfg.setdefault("lead_ms", 40)
    cfg.setdefault("bar_margin", 0.15)
    cfg.setdefault("click_cooldown_ms", 350)
    cfg.setdefault("idle_timeout_s", 1.5)
    cfg.setdefault("fish_retry_s", 4.0)
    cfg.setdefault("jitter_px", 3)
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已写入", CFG)
    print(json.dumps(cfg, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

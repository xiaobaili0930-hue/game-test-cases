"""塔塔冒险队「钓鱼大赛」自动化（微信 Mac 客户端，纯屏幕层）。

用法：
  python fish.py --dry            # 只识别状态、打印，不点击
  python fish.py --dry --debug    # 再把标注帧存到 debug/frames/
  python fish.py --replay debug/burst   # 用连拍帧离线回放，验证状态机
  python fish.py                  # 正式跑；鼠标甩到屏幕左上角=急停；Ctrl+C 退出
  python fish.py --rounds 30      # 钓 30 轮自动停

状态机（全部由按钮环颜色 + 几个采样点判定）：
  IDLE     按钮环绿   → 每 fish_retry_s 点一次按钮（抛竿）
  WAITING  按钮环灰   → 等
  BITE     按钮环亮紫 + 顶上紫色「拉钩」框 → 立刻点按钮
  PLAYING  按钮环亮紫 + 横条有深蓝轨道 → 追踪红浮标，预测 lead_ms 后落在黄区就点
  POPUP    按钮环暗紫（结算遮罩）→ 每 popup_click_s 点一下关弹窗
"""
import argparse
import glob
import json
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from screen import Screen, click, locate_window, reset_window  # noqa: E402

HERE = Path(__file__).parent
CFG = HERE / "config.json"
KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))


def inrange(hsv, rng):
    return cv2.inRange(hsv, np.array(rng[0]), np.array(rng[1]))


class Detector:
    """所有坐标按屏幕逻辑点给；frame 是 cfg['grab'] 区域的截图。"""

    def __init__(self, cfg):
        self.cfg = cfg
        gx, gy, _, _ = cfg["grab"]
        self.off = (gx, gy)
        bx, by = cfg["button"]
        r = cfg["button_ring_r"]
        ang = np.linspace(0, 2 * np.pi, 24, endpoint=False)
        self.ring = [(int(by + r * np.sin(a) - gy), int(bx + r * np.cos(a) - gx)) for a in ang]
        bx2, by2, bw2, bh2 = cfg["bite_roi"]
        self.bite_box = (slice(by2 - gy, by2 - gy + bh2), slice(bx2 - gx, bx2 - gx + bw2))
        x, y, w, h = cfg["bar_roi"]
        self.bar = (slice(y - gy, y - gy + h), slice(x - gx, x - gx + w))
        self.bar_x0 = x

    def classify(self, frame):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        ring = np.median([hsv[y, x] for y, x in self.ring], axis=0)
        h, s, v = ring
        c = self.cfg
        info = {"ring": ring.astype(int).tolist()}
        g = c["ring_green"]
        p = c["ring_purple"]
        if g[0][0] <= h <= g[1][0] and s >= g[0][1] and v >= g[0][2]:
            return "IDLE", info
        if s < c["ring_gray_max_s"] and 90 <= v <= 180:
            return "WAITING", info
        if p[0][0] <= h <= p[1][0] and s >= p[0][1]:
            if v < c["ring_dark_v"]:
                return "POPUP", info
            # 亮紫：拉钩框 or 小游戏
            sub = hsv[self.bar]
            track_m = inrange(sub, c["track_hsv"])
            track = cv2.countNonZero(track_m)
            if track >= c["track_min_px"]:
                zone = inrange(sub, c["zone_hsv"])
                bob = cv2.morphologyEx(inrange(sub, c["bobber_hsv"]), cv2.MORPH_OPEN, KERNEL)
                zx = np.flatnonzero(zone.sum(axis=0) > 0)
                info["zone"] = None if cv2.countNonZero(zone) < c["zone_min_px"] else \
                    (int(zx[0]) + self.bar_x0, int(zx[-1]) + self.bar_x0)
                # 浮标 = 最大的红色连通块（避开零星红像素/文字）
                ncc, _, stats, cent = cv2.connectedComponentsWithStats(bob)
                info["bobber"] = None
                if ncc > 1:
                    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
                    if stats[k, cv2.CC_STAT_AREA] >= c["bobber_min_px"]:
                        info["bobber"] = float(cent[k][0]) + self.bar_x0
                # 护栏：深蓝必须集中在少数几行（是一条横条），且横向上够长；
                # 同时条上得看到黄区或红浮标。否则只是蓝天/水面背景，判 PLAYING 会乱点。
                rows = int(np.count_nonzero(track_m.sum(axis=1)))
                cols = int(np.count_nonzero(track_m.sum(axis=0)))
                band_ok = rows <= c["track_max_rows"] and cols >= c["track_min_cols"]
                if band_ok and (info["zone"] is not None or info["bobber"] is not None):
                    return "PLAYING", info
            bite_px = cv2.countNonZero(inrange(hsv[self.bite_box], c["bite_hsv"]))
            if bite_px >= c["bite_min_px"]:
                return "BITE", info
            return "ACTIVE?", info
        return "UNKNOWN", info


def frames_from_screen(scr, grab, fps):
    dt = 1 / fps
    while True:
        t = time.time()
        yield time.time(), scr.grab(grab)
        spare = dt - (time.time() - t)
        if spare > 0:
            time.sleep(spare)


def frames_from_dir(d, grab, step_s=0.25):
    gx, gy, gw, gh = grab
    for i, f in enumerate(sorted(glob.glob(str(Path(d) / "*.*")))):
        im = cv2.imread(f)
        if im is None:
            continue
        yield i * step_s, im[gy:gy + gh, gx:gx + gw]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--replay", help="用目录里的全屏帧回放（隐含 --dry）")
    ap.add_argument("--rounds", type=int, default=0)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--duration", type=float, default=0, help="跑多少秒后自动停，0=不限")
    ap.add_argument("--reset-window", action="store_true", help="启动时把游戏窗口恢复到校准时的位置和大小")
    ap.add_argument("--restore-cursor", action="store_true", help="每次点完把光标移回原位，可边跑边用鼠标干别的")
    ap.add_argument("--lead-ms", type=float, help="覆盖 config 的 lead_ms 提前量")
    a = ap.parse_args()
    if a.replay:
        a.dry = True

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    if a.lead_ms is not None:
        cfg["lead_ms"] = a.lead_ms
    if not a.replay:
        # 输出同步写日志，方便事后看
        (HERE / "debug").mkdir(exist_ok=True)
        logf = open(HERE / "debug" / time.strftime("run_%m%d_%H%M%S.log"), "w", buffering=1, encoding="utf-8")

        class _Tee:
            def write(self, x):
                sys.__stdout__.write(x); logf.write(x)

            def flush(self):
                sys.__stdout__.flush(); logf.flush()
        sys.stdout = _Tee()
        print("日志:", logf.name)
        if a.reset_window:
            # 微信从小窗放大有时一次钳不到位，先挪高一点设一次再设目标位；设完等小程序重绘
            rx, ry = cfg["window_ref"]
            reset_window(cfg["window_title"], rx, max(ry - 27, 0), *cfg["window_size"])
            time.sleep(0.6)
            ok, msg = reset_window(cfg["window_title"], rx, ry, *cfg["window_size"])
            print("窗口复位:", "成功" if ok else f"失败({msg})")
            time.sleep(1.5)
        win = locate_window(cfg["window_title"])
        if win is None:
            sys.exit(f"屏幕上找不到窗口「{cfg['window_title']}」（被遮挡/最小化/不在屏上）")
        rx, ry = cfg["window_ref"]
        rw, rh = cfg["window_size"]
        sx, sy = win[2] / rw, win[3] / rh
        if abs(sx / sy - 1) > 0.03:
            sys.exit(f"窗口 {win[2]}x{win[3]} 与校准时 {rw}x{rh} 不等比，识别会错位，请把窗口拉回等比")
        if abs(sx - 1) > 0.5:
            sys.exit(f"窗口缩放 {sx:.2f} 倍过大，颜色/像素阈值不可靠，请拉回接近 {rw}x{rh}")

        def P(x, y):      # 点：窗口相对坐标按比例缩放再平移
            return [round(win[0] + (x - rx) * sx), round(win[1] + (y - ry) * sy)]

        def R(x, y, w, h):
            return P(x, y) + [round(w * sx), round(h * sy)]
        print(f"窗口在 {win[:2]} 尺寸 {win[2]}x{win[3]}，缩放 {sx:.3f}，位移 ({win[0]-rx},{win[1]-ry})")
        cfg["grab"] = R(*cfg["grab"])
        cfg["bar_roi"] = R(*cfg["bar_roi"])
        cfg["button"] = P(*cfg["button"])
        cfg["bite_roi"] = R(*cfg["bite_roi"])
        cfg["button_ring_r"] = round(cfg["button_ring_r"] * sx)
        for k in ("track_min_px", "zone_min_px", "bobber_min_px", "bite_min_px"):
            cfg[k] = round(cfg[k] * sx * sy)
        if abs(sx - 1) > 0.01:
            print(f"⚠ 窗口尺寸与校准时不同，坐标已按比例换算；若识别不准请把窗口拉回 {rw}x{rh}")
    det = Detector(cfg)
    grab = cfg["grab"]
    lead = cfg["lead_ms"] / 1000
    margin = cfg["zone_margin"]
    cooldown = cfg["click_cooldown_ms"] / 1000
    btn = cfg["button"]
    jit = cfg["jitter_px"]
    dbg_dir = HERE / "debug" / "frames"
    if a.debug:
        dbg_dir.mkdir(parents=True, exist_ok=True)
        for f in dbg_dir.glob("*.png"):
            f.unlink()

    if a.replay:
        src = frames_from_dir(a.replay, grab)
    else:
        scr = Screen()
        src = frames_from_screen(scr, grab, a.fps)
    print(f"grab={grab} dry={a.dry} replay={a.replay}")
    if not a.dry:
        print("鼠标甩到屏幕左上角可紧急停止；Ctrl+C 退出")

    def do_click(tag, now):
        print(f"[{now:7.2f}s] CLICK {tag}" + ("  (dry)" if a.dry else ""))
        if not a.dry:
            click(*btn, jitter=jit, restore=a.restore_cursor)

    state = None
    zone_mem = None
    hist = deque(maxlen=6)
    last_click = last_fish = last_popup = -1e9
    rounds = hits = n = 0
    t_start = None
    try:
        for now, frame in src:
            if t_start is None:
                t_start = now
            now -= t_start
            n += 1
            if a.duration and now > a.duration:
                break
            st, info = det.classify(frame)
            if st != state:
                print(f"[{now:7.2f}s] {state} -> {st}  ring={info['ring']}")
                if st == "PLAYING":
                    hist.clear()
                    zone_mem = None
                    last_click = -1e9      # 拉钩点击的冷却不挡开局第一击
                if st == "POPUP" and state in ("PLAYING", "ACTIVE?", "BITE"):
                    rounds += 1
                    print(f"[{now:7.2f}s] 第 {rounds} 轮结束，累计命中 {hits}")
                    if a.rounds and rounds >= a.rounds:
                        break
                state = st

            if a.debug:
                vis = frame.copy()
                cv2.putText(vis, st, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                if st == "PLAYING":
                    y0 = cfg["bar_roi"][1] - grab[1]
                    if info.get("zone"):
                        z0, z1 = [x - grab[0] for x in info["zone"]]
                        cv2.rectangle(vis, (z0, y0), (z1, y0 + 28), (0, 255, 0), 2)
                    if info.get("bobber") is not None:
                        bx = int(info["bobber"] - grab[0])
                        cv2.line(vis, (bx, y0 - 10), (bx, y0 + 40), (0, 0, 255), 2)
                cv2.imwrite(str(dbg_dir / f"{n:06d}.png"), vis)

            if st == "IDLE":
                if now - last_fish > cfg["fish_retry_s"]:
                    last_fish = now
                    do_click("抛竿", now)
            elif st == "BITE":
                if now - last_click > cooldown:
                    last_click = now
                    do_click("拉钩", now)
            elif st == "PLAYING":
                z, b = info.get("zone"), info.get("bobber")
                if b is None:
                    continue
                # 黄区记忆：浮标压在窄黄区上时黄色被盖住会检测不到/变窄，沿用上次完整看到的黄区。
                # 黄区只在命中后换位，所以每次点击后清记忆；新黄区出现在别处也替换记忆。
                if z is not None:
                    if zone_mem is None or abs(z[0] - zone_mem[0]) > 15 or (z[1] - z[0]) >= (zone_mem[1] - zone_mem[0]):
                        zone_mem = z
                    else:
                        z = zone_mem
                elif zone_mem is not None:
                    z = zone_mem
                else:
                    continue
                hist.append((now, b))
                vel = 0.0
                if len(hist) >= 2 and hist[-1][0] > hist[0][0]:
                    vel = (hist[-1][1] - hist[0][1]) / (hist[-1][0] - hist[0][0])
                pred = b + vel * lead
                w = z[1] - z[0]
                inside = z[0] + w * margin <= pred <= z[1] - w * margin
                # 浮标静止（命中后动画期）或速度离谱（误检跳点）都不点
                moving = len(hist) >= 3 and cfg["vel_min"] <= abs(vel) <= cfg["vel_max"]
                inside = inside and moving
                if a.replay or n % 10 == 0 or inside:
                    print(f"[{now:7.2f}s] bobber={b:6.1f} v={vel:6.0f}px/s pred={pred:6.1f} "
                          f"zone={z} {'HIT' if inside else ''}")
                if inside and now - last_click > cooldown:
                    last_click = now
                    hits += 1
                    do_click("命中", now)
                    hist.clear()
                    zone_mem = None
            elif st == "POPUP":
                if now - last_popup > cfg["popup_click_s"]:
                    last_popup = now
                    do_click("关弹窗", now)
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\n退出：{rounds} 轮 / {hits} 次命中 / {n} 帧")


if __name__ == "__main__":
    main()

import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import unicodedata
from io import BytesIO



def base_rate(text):
    text = unicodedata.normalize("NFKC", text).replace(" ", "")
    match = re.search(
        r"胜率[:：]?(\d{1,3})%(?:\+\d{1,3}%)?$",
        text,
    )
    if not match:
        return None

    value = int(match[1])
    return value if 0 <= value <= 100 else None


def decide(rows):
    reward_continue = [r for r in rows
        if '点击任意位置继续' in r[0].replace(' ', '')
        and r[1] >= 0.50 and 0.20 < r[2] < 0.80
        and 0.80 < r[3] < 0.98]
    if len(reward_continue) == 1:
        return '关闭宝物展示', None, 0.50, 0.50
    finished = any(
        '探险结束' in text and score >= 0.60 and y < 0.20
        for text, score, x, y in rows
    )
    collect = [r for r in rows if r[0].replace(' ', '') == '收下'
               and r[1] >= 0.50 and 0.30 < r[2] < 0.70
               and 0.80 < r[3] < 0.98]
    if finished:
        if len(collect) == 1:
            return '收下', None, collect[0][2], collect[0][3]
        return None
    home_title = any(
        '遗迹探险' in text and score >= 0.65 and y < 0.15
        for text, score, x, y in rows
    )
    home = [r for r in rows if '去探险' in r[0].replace(' ', '')
            and r[1] >= 0.55 and 0.30 < r[2] < 0.80
            and 0.75 < r[3] < 0.93]
    if home_title and len(home) == 1:
        return '去探险', None, home[0][2], home[0][3]

    def button(word, left, right):
        hits = [r for r in rows if r[0].replace(' ', '') == word
                and r[1] >= 0.50 and left < r[2] < right
                and 0.65 < r[3] < 0.92]
        return hits[0] if len(hits) == 1 else None

    fight = button('战斗', 0.55, 0.95)
    leave = button('撤离', 0.05, 0.45)
    boss_hint = any('胜率' in r[0] or r[0].strip() in ('战斗', '撤离')
                    for r in rows if r[3] > 0.5)
    if fight and leave:
        anchors = [r for r in rows if '我方胜率' in r[0].replace(' ', '')
                   and r[1] >= 0.70 and r[2] > 0.50 and r[3] > 0.75]
        values = []
        for r in rows:
            if r[1] < 0.70 or not (0.50 < r[2] < 0.98 and 0.75 < r[3] < 0.98):
                continue
            text = unicodedata.normalize('NFKC', r[0]).replace(' ', '')
            value = base_rate(text)
            if value is None and re.fullmatch(r'\d{1,3}%(?:\+\d{1,3}%)?', text):
                if any(a[2] < r[2] and abs(a[3] - r[3]) < 0.035 for a in anchors):
                    value = base_rate('胜率' + text)
            if value is not None:
                values.append(value)
        if len(values) != 1:
            return None
        rate = values[0]
        hit = fight if rate >= 30 else leave
        return ('战斗' if rate >= 30 else '撤离'), rate, hit[2], hit[3]
    if boss_hint:
        return None

    title = any('探险第' in t and '层' in t and s >= 0.60 and y < 0.15
                for t, s, x, y in rows)
    forward = [r for r in rows if r[0].replace(' ', '') == '前进'
               and r[1] >= 0.50 and 0.35 < r[2] < 0.65
               and 0.78 < r[3] < 0.92]
    if title and len(forward) == 1:
        return '前进', None, forward[0][2], forward[0][3]
    return None


def main():
    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    parser = argparse.ArgumentParser()
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    if not re.fullmatch(r"127\.0\.0\.1:\d{1,5}", args.serial):
        parser.error("连接地址应为 127.0.0.1:16416")

    def adb(*parts):
        return subprocess.run(
            [args.adb, *parts],
            check=True,
            capture_output=True,
            timeout=20,
        ).stdout

    adb("connect", args.serial)

    def device(*parts):
        return adb("-s", args.serial, *parts)

    if device("get-state").strip() != b"device":
        raise RuntimeError("未连接到模拟器，请检查 ADB 设置")

    ocr = RapidOCR()
    previous = None
    unknown = 0

    print(
        "实际点击模式" if args.run else "试运行：只识别，不点击",
        flush=True,
    )
    print("请打开游戏竖屏探险主页。按 Ctrl+C 停止。", flush=True)

    try:
        while True:
            raw = device("exec-out", "screencap", "-p")
            image = Image.open(BytesIO(raw)).convert("RGB")
            width, height = image.size

            if width >= height:
                raise RuntimeError("请将游戏切换为竖屏")

            pixels = np.array(image)[:, :, ::-1].copy()
            result, _ = ocr(pixels)

            rows = []
            for box, text, score in result or []:
                x = sum(p[0] for p in box) / 4 / width
                y = sum(p[1] for p in box) / 4 / height
                rows.append((text, float(score), x, y))

            action = decide(rows)

            if action is None:
                previous = None
                unknown += 1
                print("等待画面 / 无法可靠识别", flush=True)

                if unknown >= 12:
                    image.save("unrecognized.png")
                    Path("unrecognized.json").write_text(
                        json.dumps(rows, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print(
                        "已暂停，截图保存为 unrecognized.png。",
                        flush=True,
                    )
                    print(
                        "识别到的文字：",
                        [(r[0], round(r[1], 3)) for r in rows],
                        flush=True,
                    )
                    break
            else:
                unknown = 0
                name, rate, x, y = action

                stable = (
                    previous is not None
                    and action[:2] == previous[:2]
                    and abs(x - previous[2]) < 0.025
                    and abs(y - previous[3]) < 0.025
                )

                print(
                    f"{name}，基础胜率={rate}，"
                    f"位置=({x:.3f},{y:.3f})",
                    flush=True,
                )

                if stable and args.run:
                    device(
                        "shell", "input", "tap",
                        str(round(x * width)),
                        str(round(y * height)),
                    )
                    previous = None
                    time.sleep(5)
                else:
                    previous = action

            time.sleep(2)

    except KeyboardInterrupt:
        print("\n已停止", flush=True)


if __name__ == "__main__":
    main()
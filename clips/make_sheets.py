#!/usr/bin/env python3
"""手撮りの動画から、場面選び用の「一覧の絵」と音の大きさを作る（Mac で実行）。元の動画は外に出さない。

    python3 clips/make_sheets.py clips/inbox clips/work

- 一覧の絵（<名前>.jpg）: 1秒ごと（長い動画は最大60コマ）のコマを並べ、各コマに秒数を書く
- 音（<名前>.json）: 長さ・縦横・0.25秒ごとの音の大きさ（鳴き声などの山を探すため）
- 位置情報などの撮影データは一覧の絵に残らない（コマを描き直しているため）
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_video import ffmpeg_bin, find_font  # noqa: E402

EXTS = {".mov", ".mp4", ".m4v", ".avi", ".mkv"}
COLS, TW = 8, 240


def duration(ff: str, path: Path) -> float:
    r = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def loudness(ff: str, path: Path) -> list[float]:
    r = subprocess.run([ff, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000",
                        "-f", "s16le", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768
    hop = 2000
    return [round(float(np.sqrt(np.mean(a[i:i + hop] ** 2))), 4) for i in range(0, len(a) - hop + 1, hop)]


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg_bin()
    font = ImageFont.truetype(find_font(None), 22)
    files = sorted(p for p in src.iterdir() if p.suffix.lower() in EXTS)
    if not files:
        sys.exit(f"{src} に動画がありません")
    for p in files:
        dur = duration(ff, p)
        n = max(1, min(60, int(dur)))
        times = [dur * (i + 0.5) / n for i in range(n)]
        with tempfile.TemporaryDirectory() as t:
            frames = []
            for i, ts in enumerate(times):
                f = Path(t) / f"{i:03d}.jpg"
                subprocess.run([ff, "-v", "error", "-ss", f"{ts:.2f}", "-i", str(p), "-frames:v", "1",
                                "-vf", f"scale={TW}:-2", str(f)], check=False)
                if f.exists():
                    frames.append((ts, Image.open(f).convert("RGB")))
        if not frames:
            print(f"飛ばす（コマを取れない）: {p.name}")
            continue
        th = max(im.height for _, im in frames)
        rows = (len(frames) + COLS - 1) // COLS
        sheet = Image.new("RGB", (COLS * TW, rows * th), (20, 20, 20))
        d = ImageDraw.Draw(sheet)
        for i, (ts, im) in enumerate(frames):
            x, y = (i % COLS) * TW, (i // COLS) * th
            sheet.paste(im, (x, y))
            d.rectangle([x, y, x + 70, y + 28], fill=(0, 0, 0))
            d.text((x + 4, y + 2), f"{ts:.1f}秒", font=font, fill=(255, 255, 0))
        sheet.save(out / f"{p.stem}.jpg", quality=80)
        w, h = frames[0][1].size
        (out / f"{p.stem}.json").write_text(json.dumps({
            "file": p.name, "duration": round(dur, 2), "portrait": h > w,
            "loudness_per_0_25s": loudness(ff, p)}, ensure_ascii=False), encoding="utf-8")
        print(f"一覧を作りました: {p.name}（{dur:.1f}秒）")


if __name__ == "__main__":
    main()

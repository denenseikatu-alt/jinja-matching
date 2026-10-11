#!/usr/bin/env python3
"""手撮りの猫の動画を、計画（plan.json）どおりにつないで「まとめ動画」と「ショート」を書き出す（Mac で実行）。

    python3 clips/render_clips.py clips/work/plan.json --inbox clips/inbox -o clips/out

plan.json（場面選びはクラウドの Claude が一覧の絵を見て書く）:
    {"compilation": {"size": "landscape", "intro": ["クロちゃんの", "おもしろ場面まとめ"],
                     "segments": [{"file": "IMG_0001.MOV", "start": 2.0, "end": 8.5,
                                   "caption": "ご飯まーだー？", "heading": "その1 催促"}],
                     "youtube": {"title": "...", "description": "...", "tags": [...]}},
     "short": {"size": "portrait", ...}}

- 縦の動画を横の画面に入れるときは、同じ映像をぼかして背景に敷く（黒い帯を出さない）
- 猫の声（元の音）はそのまま、BGM（もっぴーさうんど「Escort」）を小さく重ねる
- 最初に題名の画面、最後に「猫と旅の一言シリーズ」への案内の画面を入れる
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from build_video import ffmpeg_bin, find_font  # noqa: E402

BGM = ROOT / "zatsugaku" / "assets" / "bgm" / "escort.mp3"
BGM_VOLUME = 0.10
SIZES = {"landscape": (1920, 1080), "portrait": (1080, 1920)}
ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
       "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("ffmpeg が失敗しました:\n" + r.stderr[-1500:])


def has_audio(ff: str, path: Path) -> bool:
    return "Audio:" in subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr


def fit(d: ImageDraw.ImageDraw, text: str, font_path: str, size: int, max_w: float):
    """幅に収まるまで文字を小さくする。"""
    while size > 20:
        font = ImageFont.truetype(font_path, size)
        if d.textlength(text, font=font) <= max_w:
            return font
        size = int(size * 0.9)
    return ImageFont.truetype(font_path, size)


def text_box(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, anchor: str) -> None:
    box = d.textbbox(xy, text, font=font, anchor=anchor, stroke_width=4)
    pad = 18
    d.rounded_rectangle([box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad], radius=18,
                        fill=(0, 0, 0, 150))
    d.text(xy, text, font=font, anchor=anchor, fill=(255, 255, 255), stroke_width=4, stroke_fill=(60, 40, 20))


def overlay_png(size: tuple[int, int], seg: dict, font_path: str, path: Path) -> None:
    w, h = size
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if seg.get("caption"):
        big = fit(d, seg["caption"], font_path, int(min(w, h) * 0.075), w * 0.86)
        text_box(d, (w // 2, int(h * 0.86)), seg["caption"], big, "mm")
    if seg.get("heading"):
        small = fit(d, seg["heading"], font_path, int(min(w, h) * 0.045), w * 0.8)
        text_box(d, (int(w * 0.04), int(h * 0.06)), seg["heading"], small, "lt")
    im.save(path)


def card_png(size: tuple[int, int], lines: list[str], font_path: str, path: Path) -> None:
    w, h = size
    im = Image.new("RGB", size, (250, 243, 230))
    d = ImageDraw.Draw(im)
    d.rectangle([0, int(h * 0.82), w, h], fill=(120, 84, 52))
    y0 = h * 0.45 - (len(lines) - 1) * min(w, h) * 0.06
    for i, ln in enumerate(lines):
        font = fit(d, ln, font_path, int(min(w, h) * 0.085), w * 0.86)
        d.text((w // 2, int(y0 + i * min(w, h) * 0.12)), ln, font=font, anchor="mm", fill=(80, 52, 30))
    small = ImageFont.truetype(font_path, int(min(w, h) * 0.04))
    d.text((w // 2, int(h * 0.91)), "田園生活", font=small, anchor="mm", fill=(255, 255, 255))
    im.save(path)


def render_one(name: str, spec: dict, inbox: Path, out: Path, ff: str, font_path: str) -> Path:
    size = SIZES[spec.get("size", "landscape")]
    w, h = size
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        parts = []

        def card(lines: list[str], dur: float) -> None:
            png = t / f"card{len(parts)}.png"
            card_png(size, lines, font_path, png)
            mp4 = t / f"p{len(parts):03d}.mp4"
            run([ff, "-y", "-loop", "1", "-t", f"{dur}", "-i", str(png), "-f", "lavfi", "-t", f"{dur}",
                 "-i", "anullsrc=r=48000:cl=stereo", "-shortest", *ENC, str(mp4)])
            parts.append(mp4)

        card(spec.get("intro", ["田園生活"]), 2.5)
        for seg in spec["segments"]:
            src = inbox / seg["file"]
            if not src.exists():
                sys.exit(f"元の動画がありません: {src}")
            dur = float(seg["end"]) - float(seg["start"])
            png = t / f"o{len(parts)}.png"
            overlay_png(size, seg, font_path, png)
            mp4 = t / f"p{len(parts):03d}.mp4"
            vf = (f"[0:v]split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                  f"boxblur=40:4,eq=brightness=-0.06[bg];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
                  f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30[v0];[v0][1:v]overlay=0:0[v]")
            cmd = [ff, "-y", "-ss", f"{seg['start']}", "-t", f"{dur:.3f}", "-i", str(src), "-i", str(png)]
            if has_audio(ff, src):
                amap = "0:a:0"
            else:
                cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
                amap = "2:a"
            cmd += ["-filter_complex", vf, "-map", "[v]", "-map", amap,
                    "-af", f"afade=t=in:d=0.12,afade=t=out:st={max(0, dur - 0.2):.3f}:d=0.2",
                    "-t", f"{dur:.3f}", *ENC, str(mp4)]
            run(cmd)
            parts.append(mp4)
        card(spec.get("outro", ["猫と旅の一言シリーズ", "ほかの子にも会いに来てね"]), 4.0)

        lst = t / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        joined = t / "joined.mp4"
        run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
        r = subprocess.run([ff, "-hide_banner", "-i", str(joined)], capture_output=True, text=True).stderr
        import re
        hh, mm, ss = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r).groups()
        total = int(hh) * 3600 + int(mm) * 60 + float(ss)
        dest = out / name
        dest.mkdir(parents=True, exist_ok=True)
        video = dest / "video.mp4"
        if BGM.exists():
            run([ff, "-y", "-i", str(joined), "-stream_loop", "-1", "-i", str(BGM), "-filter_complex",
                 f"[1:a]volume={BGM_VOLUME},atrim=0:{total:.3f},afade=t=out:st={max(0, total - 2):.3f}:d=2[b];"
                 f"[0:a][b]amix=inputs=2:duration=first:normalize=0[a]",
                 "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(video)])
        else:
            print("注意: BGM がありません（zatsugaku/fetch_assets.py で取れます）。BGM なしで書き出します")
            run([ff, "-y", "-i", str(joined), "-c", "copy", str(video)])
    yt = dict(spec["youtube"])
    desc = yt.get("description", "").rstrip()
    if BGM.exists():
        desc += "\n\n■ BGM\n「Escort」もっぴーさうんど（フリーBGM OpenTracks 旧DOVA-SYNDROME）"
    yt["description"] = desc
    yt.setdefault("categoryId", "15")      # ペットと動物
    yt.setdefault("privacyStatus", "private")
    (dest / "upload.json").write_text(json.dumps({"youtube": yt}, ensure_ascii=False, indent=1), encoding="utf-8")
    # upload_youtube.py は credits.txt を「■ 音声」として概要欄に入れる
    (dest / "credits.txt").write_text("撮影したときの音（猫の声など）\n", encoding="utf-8")
    print(f"書き出し: {video}（{total:.1f}秒）")
    return video


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--inbox", default="clips/inbox")
    ap.add_argument("-o", "--out", default="clips/out")
    ap.add_argument("--only", help="compilation か short だけ書き出す")
    a = ap.parse_args()
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    ff, font_path = ffmpeg_bin(), find_font(None)
    for name, spec in plan.items():
        if name.startswith("_") or (a.only and name != a.only):
            continue
        render_one(name, spec, Path(a.inbox), Path(a.out), ff, font_path)


if __name__ == "__main__":
    main()

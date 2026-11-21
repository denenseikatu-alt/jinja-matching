#!/usr/bin/env python3
"""語り手がスライドを説明する動画を、構図を切り替えながら作る。口や表情は動かさない。

    python3 build_presentation.py talk/xxx.json -o out_pres/ \\
        --poses assets_video/poses --background assets_video/room_blur.png

どのスライドにも語り手が片側に立つ。立ち位置は1枚ごとに左右が入れ替わり、ポーズは
構図に合わせて変わる（シーンの "pose" と "side" で指定もできる）。指差しや手のひらは
内容の側を向くよう、必要なら左右反転する。語り手の切り抜きは make_presenter.py で作る。

シーンごとに "layout" で構図を選ぶ:

    title     大きなタイトル                                heading, sub
    screen    見出しと箇条書き（bullets と同じ）            heading, bullets
    bullets   見出しと箇条書き                              heading, bullets
    number    大きな数字と説明                              heading, number, label, note
    table     表                                            heading, rows（1行目が見出し）
    compare   2列の比較                                     heading, left{title,items}, right{title,items}
    steps     番号付きの手順カード                          heading, steps
    checklist チェック付きのまとめ                          heading, bullets
    closing   結びの言葉                                    heading, sub

声は台本の "voice" で選ぶ。{"engine": "gemini", "name": "Leda", "style": "..."} か
{"engine": "voicevox", "speaker": 9}。lines は字幕にもなり、"caption_replace" で
字幕だけ表記を戻せる（例: {"イーピーエー": "EPA"}）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from build_video import (GAP_AFTER_LINE, GAP_AFTER_SCENE, ffmpeg_bin, find_font,
                         speaker_credit, synth as synth_voicevox, wav_duration,
                         write_silence, write_srt)
from build_talking import render_caption, wrap_ja

W, H = 1920, 1080
BG = (247, 244, 238)
PANEL = (255, 255, 255)
SOFT = (238, 232, 221)
INK = (33, 31, 30)
SUB = (106, 99, 92)
NAVY = (29, 53, 87)
WARM = (190, 104, 72)
CONTENT_BOTTOM = 860      # これより下は字幕の帯


# ポーズごとの既定。gesture は手ぶりが向く側（元画像で見て）。説明の内容がある側を向くよう、
# 立ち位置に応じて左右反転する
POSES = {
    "present": {"gesture": "left"},
    "point": {"gesture": "right"},
    "surprised": {"gesture": None},
    "think": {"gesture": None},
    "hands": {"gesture": None},
    "thumbsup": {"gesture": None},
}
LAYOUT_POSE = {"title": "present", "screen": "point", "bullets": "point", "number": "surprised",
               "table": "point", "compare": "think", "steps": "present", "checklist": "thumbsup",
               "closing": "hands"}


class Painter:
    """スライドを描く。すべての構図で、語り手が片側に立って説明する。"""

    def __init__(self, font_path: str, background: Image.Image, poses: dict, site: str):
        self.fp = font_path
        self.bg = background
        self.poses = poses
        self.site = site
        self._fonts: dict[int, ImageFont.FreeTypeFont] = {}

    def f(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(self.fp, size)
        return self._fonts[size]

    # --- 共通の部品 -------------------------------------------------------
    def canvas(self, s: dict, i: int) -> tuple[Image.Image, ImageDraw.ImageDraw, tuple]:
        """背景・語り手・内容用のパネルを置き、パネルの内側の範囲を返す。"""
        img = self.bg.copy()
        side = s.get("side") or ("left" if i % 2 else "right")
        pose = s.get("pose") or LAYOUT_POSE.get(s.get("layout", "bullets"), "present")
        pw = 1180                                  # パネルの幅
        if side == "left":
            box = (W - 70 - pw, 70, W - 70, CONTENT_BOTTOM)
        else:
            box = (70, 70, 70 + pw, CONTENT_BOTTOM)
        panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        pd = ImageDraw.Draw(panel)
        pd.rounded_rectangle([box[0] + 8, box[1] + 12, box[2] + 8, box[3] + 12], radius=34,
                             fill=(0, 0, 0, 40))
        panel = panel.filter(ImageFilter.GaussianBlur(10))
        pd = ImageDraw.Draw(panel)
        pd.rounded_rectangle(box, radius=34, fill=(255, 255, 255, 242))
        pd.rounded_rectangle([box[0], box[1], box[2], box[1] + 14], radius=7, fill=NAVY + (255,))
        img.paste(panel, (0, 0), panel)
        self.place_presenter(img, pose, side)
        d = ImageDraw.Draw(img)
        d.text((box[0] + 50, box[1] + 36), self.site, font=self.f(24), fill=SUB)
        inner = (box[0] + 60, box[1] + 90, box[2] - 60, box[3] - 40)
        return img, d, inner

    def place_presenter(self, img: Image.Image, pose: str, side: str) -> None:
        fig = self.poses.get(pose) or next(iter(self.poses.values()))
        gesture = POSES.get(pose, {}).get("gesture")
        # 左に立つなら手ぶりは右（内容の側）へ、右に立つなら左へ向ける
        want = "right" if side == "left" else "left"
        if gesture and gesture != want:
            fig = fig.transpose(Image.FLIP_LEFT_RIGHT)
        h = 930
        fig = fig.resize((int(fig.width * h / fig.height), h), Image.LANCZOS)
        x = 40 if side == "left" else W - 40 - fig.width
        img.paste(fig, (x, H - h + 30), fig)

    def heading(self, d, text, box, size=54) -> int:
        x0, y, x1, _ = box
        for row in wrap_ja(d, text, self.f(size), x1 - x0)[:2]:
            d.text((x0, y), row, font=self.f(size), fill=INK)
            y += int(size * 1.3)
        d.rectangle([x0, y + 6, x0 + 100, y + 12], fill=WARM)
        return y + 44

    def bullets(self, d, items, x, y, max_w, size=40, mark="dot") -> int:
        f = self.f(size)
        indent = int(size * 1.3)
        for b in items:
            rows = wrap_ja(d, b, f, max_w - indent)
            cy = y + size * 0.58
            if mark == "check":
                r = size * 0.42
                d.rounded_rectangle([x, cy - r, x + 2 * r, cy + r], radius=6, fill=NAVY)
                d.line([x + r * 0.45, cy, x + r * 0.9, cy + r * 0.45, x + r * 1.6, cy - r * 0.5],
                       fill=PANEL, width=5)
            else:
                r = size * 0.18
                d.ellipse([x + 4, cy - r, x + 4 + 2 * r, cy + r], fill=WARM)
            for row in rows[:3]:
                d.text((x + indent, y), row, font=f, fill=INK)
                y += int(size * 1.4)
            y += int(size * 0.5)
        return y

    # --- 構図 -------------------------------------------------------------
    def title(self, s, i, n):
        img, d, (x0, y0, x1, y1) = self.canvas(s, i)
        y = y0 + 110
        for row in wrap_ja(d, s["heading"], self.f(74), x1 - x0)[:3]:
            d.text((x0, y), row, font=self.f(74), fill=INK)
            y += 98
        d.rectangle([x0, y + 14, x0 + 140, y + 22], fill=WARM)
        if s.get("sub"):
            y += 60
            for row in wrap_ja(d, s["sub"], self.f(40), x1 - x0)[:2]:
                d.text((x0, y), row, font=self.f(40), fill=SUB)
                y += 56
        return img

    closing = title

    def bullets_(self, s, i, n):
        img, d, box = self.canvas(s, i)
        y = self.heading(d, s["heading"], box)
        self.bullets(d, s.get("bullets", []), box[0], y + 6, box[2] - box[0], size=42)
        return img

    screen_ = bullets_

    def checklist(self, s, i, n):
        img, d, box = self.canvas(s, i)
        y = self.heading(d, s["heading"], box)
        self.bullets(d, s.get("bullets", []), box[0], y + 6, box[2] - box[0], size=40,
                     mark="check")
        return img

    def number(self, s, i, n):
        img, d, box = self.canvas(s, i)
        x0, _, x1, y1 = box
        y = self.heading(d, s["heading"], box, size=48)
        nb = (x0, y, x0 + 470, y1)
        d.rounded_rectangle(nb, radius=30, fill=NAVY)
        num = s["number"]
        size = 150
        while d.textlength(num, font=self.f(size)) > 420 and size > 60:
            size -= 6
        cx = (nb[0] + nb[2]) / 2
        ny = y + 60
        d.text((cx - d.textlength(num, font=self.f(size)) / 2, ny), num, font=self.f(size),
               fill=PANEL)
        ly = ny + size + 30
        for row in wrap_ja(d, s.get("label", ""), self.f(32), 420)[:3]:
            d.text((cx - d.textlength(row, font=self.f(32)) / 2, ly), row, font=self.f(32),
                   fill=(222, 228, 238))
            ly += 44
        ty = y + 10
        for para in s.get("note", "").split("\n"):
            for row in wrap_ja(d, para, self.f(34), x1 - x0 - 510):
                d.text((x0 + 510, ty), row, font=self.f(34), fill=INK)
                ty += 50
            ty += 22
        return img

    def table(self, s, i, n):
        img, d, box = self.canvas(s, i)
        x0, _, x1, y1 = box
        y = self.heading(d, s["heading"], box, size=48)
        rows = s["rows"]
        widths = s.get("widths") or [1] * max(len(r) for r in rows)
        xs = [x0]
        for wv in widths:
            xs.append(xs[-1] + (x1 - x0) * wv / sum(widths))
        size = 28 if len(rows) <= 5 else 26
        rh = min(104, (y1 - y) // len(rows))
        for r, row in enumerate(rows):
            top = y + r * rh
            fill = NAVY if r == 0 else (PANEL if r % 2 else SOFT)
            d.rectangle([x0, top, x1, top + rh - 4], fill=fill)
            for c, cell in enumerate(row):
                lines = wrap_ja(d, cell, self.f(size), int(xs[c + 1] - xs[c] - 28))[:3]
                ty = top + (rh - 4 - len(lines) * size * 1.25) / 2
                for ln in lines:
                    d.text((xs[c] + 14, ty), ln, font=self.f(size), fill=PANEL if r == 0 else INK)
                    ty += size * 1.25
        return img

    def compare(self, s, i, n):
        img, d, box = self.canvas(s, i)
        x0, _, x1, y1 = box
        y = self.heading(d, s["heading"], box, size=48)
        gap = 30
        cw = (x1 - x0 - gap) / 2
        for k, side in enumerate((s["left"], s["right"])):
            a = x0 + k * (cw + gap)
            b = a + cw
            color = NAVY if k == 0 else WARM
            d.rounded_rectangle([a, y, b, y1], radius=26, fill=PANEL, outline=color, width=4)
            d.rounded_rectangle([a, y, b, y + 84], radius=26, fill=color)
            d.rectangle([a, y + 50, b, y + 84], fill=color)
            tw = d.textlength(side["title"], font=self.f(38))
            d.text(((a + b) / 2 - tw / 2, y + 20), side["title"], font=self.f(38), fill=PANEL)
            self.bullets(d, side.get("items", []), a + 30, y + 110, cw - 50, size=32)
        return img

    def steps(self, s, i, n):
        img, d, box = self.canvas(s, i)
        x0, _, x1, y1 = box
        y = self.heading(d, s["heading"], box, size=48)
        items = s["steps"]
        cols = 2 if len(items) == 4 else len(items)
        rows = (len(items) + cols - 1) // cols
        gap = 26
        cw = (x1 - x0 - gap * (cols - 1)) / cols
        ch = (y1 - y - gap * (rows - 1)) / rows
        for j, text in enumerate(items):
            r, c = divmod(j, cols)
            a, t = x0 + c * (cw + gap), y + r * (ch + gap)
            d.rounded_rectangle([a, t, a + cw, t + ch], radius=24, fill=SOFT)
            d.ellipse([a + 24, t + 24, a + 94, t + 94], fill=NAVY if j % 2 == 0 else WARM)
            num = str(j + 1)
            d.text((a + 59 - d.textlength(num, font=self.f(44)) / 2, t + 34), num,
                   font=self.f(44), fill=PANEL)
            head, *rest = text.split("\n")
            ty = t + 30
            for row in wrap_ja(d, head, self.f(34), int(cw - 140))[:2]:
                d.text((a + 116, ty), row, font=self.f(34), fill=INK)
                ty += 46
            ty = max(ty, t + 110)
            for para in rest:
                for row in wrap_ja(d, para, self.f(28), int(cw - 48))[:3]:
                    d.text((a + 26, ty), row, font=self.f(28), fill=SUB)
                    ty += 40
        return img

    def render(self, s: dict, i: int, n: int) -> Image.Image:
        fn = {"title": self.title, "closing": self.closing, "screen": self.screen_,
              "bullets": self.bullets_, "checklist": self.checklist, "number": self.number,
              "table": self.table, "compare": self.compare, "steps": self.steps}
        layout = s.get("layout", "bullets")
        if layout not in fn:
            sys.exit(f"未知の layout です: {layout}（scene {i}）")
        return fn[layout](s, i, n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script")
    ap.add_argument("-o", "--outdir", default="out_pres")
    ap.add_argument("--background", default="assets_video/room_blur.png",
                    help="背景（ぼかしたセミナー室など）")
    ap.add_argument("--poses", default="assets_video/poses",
                    help="語り手の切り抜き（make_presenter.py の出力）のフォルダ")
    ap.add_argument("--host", default="http://127.0.0.1:50021")
    ap.add_argument("--font", default=None)
    ap.add_argument("--slides-only", action="store_true", help="スライド画像だけ出す")
    args = ap.parse_args()

    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    scenes = script["scenes"]
    voice = script.get("voice", {"engine": "voicevox", "speaker": script.get("speaker", 9)})
    font_path = find_font(args.font)
    background = Image.open(args.background).convert("RGB").resize((W, H), Image.LANCZOS)
    poses = {p.stem: Image.open(p).convert("RGBA") for p in sorted(Path(args.poses).glob("*.png"))}
    if not poses:
        sys.exit(f"語り手の切り抜きがありません: {args.poses}（make_presenter.py で作る）")
    site = script.get("site") or script.get("site_host") or urllib.parse.urlparse(
        script.get("source_url", "")).netloc
    painter = Painter(font_path, background, poses, site)

    outdir = Path(args.outdir)
    slides_dir, audio_dir, frames_dir = outdir / "slides", outdir / "audio", outdir / "frames"
    for p in (slides_dir, audio_dir, frames_dir):
        p.mkdir(parents=True, exist_ok=True)

    slides = []
    for i, s in enumerate(scenes, 1):
        img = painter.render(s, i, len(scenes))
        p = slides_dir / f"{i:02d}.png"
        img.save(p)
        slides.append(img)
    print(f"スライド {len(slides)} 枚 → {slides_dir}")
    if args.slides_only:
        return

    # 音声（1行 = 1ファイル）。字幕は実測の長さで並べる
    if voice.get("engine") == "gemini":
        import tts_gemini

        def say(text: str, path: Path) -> None:
            tts_gemini.synth(text, path, voice=voice.get("name", "Leda"),
                             style=voice.get("style", ""))
        credit = tts_gemini.CREDIT
    else:
        speaker = voice.get("speaker", 9)

        def say(text: str, path: Path) -> None:
            synth_voicevox(text, speaker, args.host, path)
        credit = speaker_credit(speaker, args.host)

    # Gemini は1日の回数制限が厳しいので、数場面ぶん（約600字）をまとめて1回で作る
    if voice.get("engine") == "gemini":
        tts_gemini.synth_script(scenes, audio_dir, voice)

    replace = script.get("caption_replace", {})
    timeline, frames, subtitles, spans = [], [], [], []
    clock, n, first = 0.0, 0, None
    silence: dict[float, Path] = {}
    for si, s in enumerate(scenes):
        start = clock
        for li, line in enumerate(s["lines"]):
            n += 1
            wav = audio_dir / f"{n:04d}.wav"
            if not wav.exists():          # 途中で止まっても合成済みの行は使い回す
                say(line, wav)
            first = first or wav
            dur = wav_duration(wav)
            gap = GAP_AFTER_SCENE if li == len(s["lines"]) - 1 else GAP_AFTER_LINE
            if gap not in silence:
                silence[gap] = audio_dir / f"sil_{int(gap * 1000)}.wav"
                write_silence(silence[gap], gap, first)
            shown = line
            for a, b in replace.items():
                shown = shown.replace(a, b)
            subtitles.append((clock, clock + dur, shown))
            frame = slides[si].copy()
            cap = render_caption(shown, font_path)
            frame.paste(cap, (0, 0), cap)
            fp = frames_dir / f"{n:04d}.png"
            frame.save(fp)
            frames.append((fp, dur + gap))
            timeline += [wav, silence[gap]]
            clock += dur + gap
        spans.append((start, clock))
        print(f"  [{si + 1}/{len(scenes)}] {s['heading']} — {clock - start:.1f}s", flush=True)
    total = clock

    (outdir / "audio.txt").write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in timeline), encoding="utf-8")
    img_list = "".join(f"file '{p.resolve().as_posix()}'\nduration {d:.3f}\n" for p, d in frames)
    img_list += f"file '{frames[-1][0].resolve().as_posix()}'\n"
    (outdir / "images.txt").write_text(img_list, encoding="utf-8")
    mp4 = outdir / "video.mp4"
    subprocess.run([
        ffmpeg_bin(), "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(outdir / "images.txt"),
        "-f", "concat", "-safe", "0", "-i", str(outdir / "audio.txt"),
        "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.3f}", str(mp4)], check=True)

    write_srt(subtitles, outdir / "video.srt")
    (outdir / "credits.txt").write_text(credit + "\n", encoding="utf-8")
    chapters = []
    for s, (a, _) in zip(scenes, spans):
        m, sec = divmod(int(a), 60)
        chapters.append(f"{m:02d}:{sec:02d} {s['heading']}")
    (outdir / "chapters.txt").write_text("\n".join(chapters) + "\n", encoding="utf-8")
    mins, secs = divmod(total, 60)
    print(f"\n完成: {mp4}")
    print(f"クレジット: {credit}")
    print(f"尺: {int(mins)}分{secs:04.1f}秒 / スライド {len(scenes)} 枚")


if __name__ == "__main__":
    main()

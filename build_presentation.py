#!/usr/bin/env python3
"""語り手がスライドを説明する動画を、構図を切り替えながら作る。口や表情は動かさない。

    python3 build_presentation.py talk/xxx.json -o out_pres/ \\
        --scene assets_video/presenter2.png --layout assets_video/presenter2.json

シーンごとに "layout" で構図を選ぶ:

    title     語り手の横のスクリーンに大きくタイトル        heading, sub
    screen    語り手の横のスクリーンに見出しと箇条書き      heading, bullets
    bullets   左に箇条書き、右に語り手                      heading, bullets
    number    大きな数字と説明                              heading, number, label, note
    table     表                                            heading, rows（1行目が見出し）
    compare   2列の比較                                     heading, left{title,items}, right{title,items}
    steps     番号付きの手順カード                          heading, steps
    checklist チェック付きのまとめ、左に語り手              heading, bullets
    closing   スクリーンに結びの言葉と記事の案内            heading, sub

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


class Painter:
    def __init__(self, font_path: str, scene_img: Image.Image, layout: dict, site: str):
        self.fp = font_path
        self.scene = scene_img
        self.screen = layout["screen"]
        self.person = layout["person"]
        self.site = site
        self._fonts: dict[int, ImageFont.FreeTypeFont] = {}

    def f(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(self.fp, size)
        return self._fonts[size]

    # --- 共通の部品 -------------------------------------------------------
    def base(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, 10], fill=NAVY)
        d.text((80, 38), self.site, font=self.f(26), fill=SUB)
        return img, d

    def number_badge(self, d: ImageDraw.ImageDraw, idx: int, total: int) -> None:
        t = f"{idx:02d} / {total:02d}"
        d.text((W - 80 - d.textlength(t, font=self.f(24)), 40), t, font=self.f(24), fill=SUB)

    def heading(self, d: ImageDraw.ImageDraw, text: str, x: int, y: int, max_w: int,
                size: int = 60) -> int:
        for row in wrap_ja(d, text, self.f(size), max_w)[:2]:
            d.text((x, y), row, font=self.f(size), fill=INK)
            y += int(size * 1.3)
        d.rectangle([x, y + 8, x + 110, y + 14], fill=WARM)
        return y + 50

    def bullets(self, d: ImageDraw.ImageDraw, items: list[str], x: int, y: int, max_w: int,
                size: int = 42, mark: str = "dot") -> int:
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

    def person_card(self, img: Image.Image, box: tuple[int, int, int, int]) -> None:
        """シーン画像から語り手の部分を切り出し、角丸のカードとして置く。"""
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        px0, py0, px1, py1 = self.person
        crop = self.scene.crop((px0, py0, px1, py1))
        # 箱の縦横比に合わせて中央（やや上）で切りそろえる
        cw, ch = crop.size
        if cw / ch > bw / bh:
            nw = int(ch * bw / bh)
            crop = crop.crop(((cw - nw) // 2, 0, (cw - nw) // 2 + nw, ch))
        else:
            nh = int(cw * bh / bw)
            crop = crop.crop((0, 0, cw, nh))
        crop = crop.resize((bw, bh), Image.LANCZOS)
        mask = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=28, fill=255)
        shadow = Image.new("RGBA", (bw + 40, bh + 40), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle([20, 26, bw + 20, bh + 26], radius=28,
                                                 fill=(0, 0, 0, 60))
        shadow = shadow.filter(ImageFilter.GaussianBlur(12))
        img.paste(shadow, (x0 - 20, y0 - 20), shadow)
        img.paste(crop, (x0, y0), mask)

    def on_screen(self) -> tuple[Image.Image, ImageDraw.ImageDraw, tuple[int, int, int, int]]:
        img = self.scene.copy()
        d = ImageDraw.Draw(img)
        x0, y0, x1, y1 = self.screen
        d.rectangle([x0, y0, x1, y1], fill=(250, 250, 248))
        d.rectangle([x0, y0, x1, y0 + 12], fill=NAVY)
        return img, d, (x0, y0, x1, y1)

    # --- 構図 -------------------------------------------------------------
    def title(self, s: dict, i: int, n: int) -> Image.Image:
        img, d, (x0, y0, x1, y1) = self.on_screen()
        pad = int((x1 - x0) * 0.08)
        y = y0 + int((y1 - y0) * 0.22)
        d.text((x0 + pad, y), self.site, font=self.f(30), fill=WARM)
        y += 64
        for row in wrap_ja(d, s["heading"], self.f(64), x1 - x0 - 2 * pad)[:3]:
            d.text((x0 + pad, y), row, font=self.f(64), fill=INK)
            y += 84
        if s.get("sub"):
            y += 16
            for row in wrap_ja(d, s["sub"], self.f(34), x1 - x0 - 2 * pad)[:2]:
                d.text((x0 + pad, y), row, font=self.f(34), fill=SUB)
                y += 48
        return img

    def closing(self, s: dict, i: int, n: int) -> Image.Image:
        return self.title(s, i, n)

    def screen_(self, s: dict, i: int, n: int) -> Image.Image:
        img, d, (x0, y0, x1, y1) = self.on_screen()
        pad = int((x1 - x0) * 0.07)
        sw = x1 - x0 - 2 * pad
        y = y0 + int((y1 - y0) * 0.1)
        for row in wrap_ja(d, s["heading"], self.f(48), sw)[:2]:
            d.text((x0 + pad, y), row, font=self.f(48), fill=INK)
            y += 64
        d.rectangle([x0 + pad, y + 6, x0 + pad + 90, y + 11], fill=WARM)
        self.bullets(d, s.get("bullets", []), x0 + pad, y + 40, sw, size=34)
        return img

    def bullets_(self, s: dict, i: int, n: int) -> Image.Image:
        img, d = self.base()
        self.number_badge(d, i, n)
        y = self.heading(d, s["heading"], 110, 120, 1020)
        self.bullets(d, s.get("bullets", []), 120, y + 10, 1000)
        self.person_card(img, (1250, 120, 1810, CONTENT_BOTTOM))
        return img

    def checklist(self, s: dict, i: int, n: int) -> Image.Image:
        img, d = self.base()
        self.number_badge(d, i, n)
        self.person_card(img, (110, 120, 640, CONTENT_BOTTOM))
        y = self.heading(d, s["heading"], 740, 120, 1080)
        self.bullets(d, s.get("bullets", []), 750, y + 10, 1060, size=40, mark="check")
        return img

    def number(self, s: dict, i: int, n: int) -> Image.Image:
        img, d = self.base()
        self.number_badge(d, i, n)
        self.heading(d, s["heading"], 110, 120, 1700, size=54)
        d.rounded_rectangle([110, 300, 930, CONTENT_BOTTOM - 20], radius=36, fill=NAVY)
        num = s["number"]
        size = 200
        while d.textlength(num, font=self.f(size)) > 700 and size > 80:
            size -= 10
        tw = d.textlength(num, font=self.f(size))
        d.text((520 - tw / 2, 400), num, font=self.f(size), fill=PANEL)
        if s.get("label"):
            for k, row in enumerate(wrap_ja(d, s["label"], self.f(40), 720)[:2]):
                lw = d.textlength(row, font=self.f(40))
                d.text((520 - lw / 2, 400 + size + 40 + k * 56), row, font=self.f(40),
                       fill=(222, 228, 238))
        y = 330
        for para in s.get("note", "").split("\n"):
            for row in wrap_ja(d, para, self.f(40), 780):
                d.text((1010, y), row, font=self.f(40), fill=INK)
                y += 60
            y += 24
        return img

    def table(self, s: dict, i: int, n: int) -> Image.Image:
        img, d = self.base()
        self.number_badge(d, i, n)
        y = self.heading(d, s["heading"], 110, 120, 1700, size=54)
        rows = s["rows"]
        ncol = max(len(r) for r in rows)
        widths = s.get("widths") or [1] * ncol
        total = sum(widths)
        x0, x1 = 110, W - 110
        xs = [x0]
        for wv in widths:
            xs.append(xs[-1] + (x1 - x0) * wv / total)
        size = 34 if len(rows) <= 6 else 30
        avail = CONTENT_BOTTOM - 20 - y
        rh = min(96, avail // len(rows))
        for r, row in enumerate(rows):
            top = y + r * rh
            fill = NAVY if r == 0 else (PANEL if r % 2 else SOFT)
            d.rectangle([x0, top, x1, top + rh - 4], fill=fill)
            for c, cell in enumerate(row):
                lines = wrap_ja(d, cell, self.f(size), int(xs[c + 1] - xs[c] - 36))[:2]
                ty = top + (rh - 4 - len(lines) * size * 1.25) / 2
                for ln in lines:
                    d.text((xs[c] + 18, ty), ln, font=self.f(size),
                           fill=PANEL if r == 0 else INK)
                    ty += size * 1.25
        return img

    def compare(self, s: dict, i: int, n: int) -> Image.Image:
        img, d = self.base()
        self.number_badge(d, i, n)
        y = self.heading(d, s["heading"], 110, 120, 1700, size=54)
        for k, side in enumerate((s["left"], s["right"])):
            x0 = 110 + k * 870
            x1 = x0 + 830
            color = NAVY if k == 0 else WARM
            d.rounded_rectangle([x0, y, x1, CONTENT_BOTTOM - 10], radius=30, fill=PANEL,
                                outline=color, width=4)
            d.rounded_rectangle([x0, y, x1, y + 96], radius=30, fill=color)
            d.rectangle([x0, y + 60, x1, y + 96], fill=color)
            tw = d.textlength(side["title"], font=self.f(44))
            d.text(((x0 + x1) / 2 - tw / 2, y + 22), side["title"], font=self.f(44), fill=PANEL)
            self.bullets(d, side.get("items", []), x0 + 40, y + 130, 750, size=38)
        return img

    def steps(self, s: dict, i: int, n: int) -> Image.Image:
        img, d = self.base()
        self.number_badge(d, i, n)
        y = self.heading(d, s["heading"], 110, 120, 1700, size=54)
        items = s["steps"]
        k = len(items)
        gap = 40
        cw = (W - 220 - gap * (k - 1)) / k
        for j, text in enumerate(items):
            x0 = 110 + j * (cw + gap)
            d.rounded_rectangle([x0, y + 20, x0 + cw, CONTENT_BOTTOM - 10], radius=30,
                                fill=PANEL)
            cx = x0 + cw / 2
            d.ellipse([cx - 52, y + 60, cx + 52, y + 164], fill=NAVY if j % 2 == 0 else WARM)
            num = str(j + 1)
            d.text((cx - d.textlength(num, font=self.f(60)) / 2, y + 74), num,
                   font=self.f(60), fill=PANEL)
            ty = y + 200
            # 1行目はカードの見出し、改行以降は小さめの補足
            head, *rest = text.split("\n")
            for row in wrap_ja(d, head, self.f(38), int(cw - 60))[:4]:
                d.text((x0 + 30, ty), row, font=self.f(38), fill=INK)
                ty += 56
            ty += 14
            for para in rest:
                for row in wrap_ja(d, para, self.f(31), int(cw - 60))[:4]:
                    d.text((x0 + 30, ty), row, font=self.f(31), fill=SUB)
                    ty += 46
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
    ap.add_argument("--scene", default="assets_video/presenter2.png",
                    help="語り手とスクリーンが写った 16:9 の絵")
    ap.add_argument("--layout", default="assets_video/presenter2.json")
    ap.add_argument("--host", default="http://127.0.0.1:50021")
    ap.add_argument("--font", default=None)
    ap.add_argument("--slides-only", action="store_true", help="スライド画像だけ出す")
    args = ap.parse_args()

    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    scenes = script["scenes"]
    voice = script.get("voice", {"engine": "voicevox", "speaker": script.get("speaker", 9)})
    font_path = find_font(args.font)
    scene_img = Image.open(args.scene).convert("RGB").resize((W, H), Image.LANCZOS)
    layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    site = script.get("site") or script.get("site_host") or urllib.parse.urlparse(
        script.get("source_url", "")).netloc
    painter = Painter(font_path, scene_img, layout, site)

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
        chunk, count = [], 0
        k = 0
        def flush(chunk):
            todo = [(line, audio_dir / f"{idx:04d}.wav") for idx, line in chunk]
            if any(not p.exists() for _, p in todo):
                tts_gemini.synth_lines([l for l, _ in todo], [p for _, p in todo],
                                       voice=voice.get("name", "Leda"),
                                       style=voice.get("style", ""))
                print(f"  音声 {todo[0][1].stem}〜{todo[-1][1].stem} を生成", flush=True)
        for s in scenes:
            scene_lines = []
            for line in s["lines"]:
                k += 1
                scene_lines.append((k, line))
            size = sum(len(l) for _, l in scene_lines)
            if chunk and count + size > 600:
                flush(chunk)
                chunk, count = [], 0
            chunk += scene_lines
            count += size
        if chunk:
            flush(chunk)

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

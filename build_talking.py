#!/usr/bin/env python3
"""語り手がスクリーンの横で解説する形式の動画を作る。

    python3 build_talking.py script.json -o out_talk/ \\
        --presenter assets_video/presenter.png --layout assets_video/presenter.json

- 声は build_video.py と同じく VOICEVOX で1行ずつ合成し、実測の長さで並べる
- 口は音声の大きさに合わせて開閉する（1枚絵の口の位置に口の形を描く）
- まばたきは不規則な間隔で入れる
- カメラはほぼ固定で、ごくわずかに寄り引きする
- 各シーンの heading / bullets を、絵の中のスクリーンに映す
- lines を字幕として画面下に焼き込む（video.srt も出す）。読みを開いた語は、台本の
  "caption_replace"（例: {"イーピーエー": "EPA"}）で字幕だけ元の表記に戻せる

layout（JSON）には絵の中の位置を 1920×1080 基準のピクセルで書く:
    {"screen": [x0, y0, x1, y1],
     "mouth": {"cx": .., "cy": .., "w": .., "angle": ..},   # 口の中心は唇の合わせ目
     "eyes": [{"cx": .., "cy": .., "w": .., "h": .., "angle": .., "skin": [x, y]}, ...]}
angle は顔の傾き（度・反時計回り）。skin はまぶたの色を取る頬の位置。

これは AI の動画生成ではない。口・まばたき・寄り引き以外（手振り・首の動き）は動かない。
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from build_video import (GAP_AFTER_LINE, GAP_AFTER_SCENE, ffmpeg_bin, find_font,
                         speaker_credit, synth, wav_duration, wrap, write_silence,
                         write_srt)

W, H = 1920, 1080
FPS = 30
SCREEN_BG = (250, 250, 248)
INK = (31, 28, 26)
ACCENT = (27, 54, 93)       # 紺（スーツに合わせる）


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data.astype(np.float32) / 32768.0, rate


def mouth_levels(samples: np.ndarray, rate: int, n_frames: int) -> np.ndarray:
    """フレームごとの口の開き（0〜1）。音量の包絡線を正規化し、少しなめらかにする。"""
    hop = rate / FPS
    rms = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        seg = samples[int(i * hop):int((i + 1) * hop)]
        if seg.size:
            rms[i] = math.sqrt(float(np.mean(seg * seg)))
    voiced = rms[rms > 0.01]
    ref = float(np.percentile(voiced, 90)) if voiced.size else 1.0
    level = np.clip((rms - 0.012) / max(ref - 0.012, 1e-6), 0.0, 1.0)
    # 開きっぱなしに見えないよう、母音の粒ごとに少し揺らす
    out = np.zeros_like(level)
    prev = 0.0
    for i, v in enumerate(level):
        prev = prev * 0.35 + v * 0.65
        out[i] = prev
    return out


def blink_schedule(n_frames: int, seed: int = 7) -> dict[int, float]:
    """フレーム番号 → まぶたの閉じ具合（0〜1）。2.5〜5.5秒おきに約0.15秒のまばたき。"""
    rng = random.Random(seed)
    shape = [0.55, 0.95, 0.95, 0.55]
    sched: dict[int, float] = {}
    t = rng.uniform(1.0, 2.5)
    while True:
        start = int(t * FPS)
        if start + len(shape) >= n_frames:
            return sched
        for k, v in enumerate(shape):
            sched[start + k] = v
        t += rng.uniform(2.5, 5.5)


def render_screen(scene: dict, size: tuple[int, int], font_path: str) -> Image.Image:
    """スクリーンに映すスライド。見出しと箇条書きだけの簡素なもの。"""
    sw, sh = size
    img = Image.new("RGB", size, SCREEN_BG)
    d = ImageDraw.Draw(img)
    pad = int(sw * 0.07)
    hf = ImageFont.truetype(font_path, max(18, int(sh * 0.12)))
    bf = ImageFont.truetype(font_path, max(14, int(sh * 0.085)))
    d.rectangle([0, 0, sw, int(sh * 0.025)], fill=ACCENT)
    y = int(sh * 0.12)
    for line in wrap_ja(d, scene["heading"], hf, sw - pad * 2)[:3]:
        d.text((pad, y), line, font=hf, fill=INK)
        y += int(hf.size * 1.35)
    d.rectangle([pad, y + 4, pad + int(sw * 0.1), y + 8], fill=ACCENT)
    y += int(sh * 0.08)
    for b in scene.get("bullets", [])[:5]:
        rows = wrap_ja(d, b, bf, sw - pad * 2 - int(bf.size * 1.2))
        r = bf.size * 0.22
        cy = y + bf.size * 0.6
        d.ellipse([pad, cy - r, pad + 2 * r, cy + r], fill=ACCENT)
        for row in rows[:3]:
            d.text((pad + int(bf.size * 1.2), y), row, font=bf, fill=INK)
            y += int(bf.size * 1.4)
        y += int(bf.size * 0.45)
    return img


NO_LINE_START = "、。，．・：；？！」』）】〕ー々ぁぃぅぇぉっゃゅょァィゥェォッャュョ"


def wrap_ja(d: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
            max_w: int) -> list[str]:
    """wrap() の結果に行頭禁則をかける（句読点や小書き文字を前の行へ送る）。"""
    rows = wrap(d, text, font, max_w)
    for i in range(1, len(rows)):
        while rows[i] and rows[i][0] in NO_LINE_START:
            rows[i - 1] += rows[i][0]
            rows[i] = rows[i][1:]
    return [r for r in rows if r]


def render_caption(text: str, font_path: str) -> Image.Image:
    """字幕レイヤー（RGBA）。画面下に半透明の帯を敷いて白文字で出す。"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = ImageFont.truetype(font_path, 50)
    rows = wrap_ja(d, text, f, W - 360)[:2]
    lh = 66
    band_h = lh * len(rows) + 44
    top = H - band_h - 36
    d.rounded_rectangle([140, top, W - 140, top + band_h], radius=18, fill=(15, 18, 28, 170))
    y = top + 22
    for row in rows:
        tw = d.textlength(row, font=f)
        d.text(((W - tw) / 2, y), row, font=f, fill=(255, 255, 255, 255))
        y += lh
    return layer


class Face:
    """1枚絵の口とまぶたを描き替える。顔の傾き（angle, 度・反時計回り）に合わせて描く。"""

    def __init__(self, base: Image.Image, layout: dict):
        self.mouth = layout["mouth"]
        self.eyes = layout.get("eyes", [])
        px = base.load()

        def sample(x: int, y: int) -> tuple[int, int, int]:
            # 前髪やまつげの暗い画素を除いて、明るい肌だけを平均する
            vals = [px[x + dx, y + dy] for dx in range(-4, 5) for dy in range(-4, 5)]
            light = [v for v in vals if sum(v) / 3 > 170] or vals
            return tuple(sum(v[i] for v in light) // len(light) for i in range(3))

        # まぶたの色は、目のすぐ上（まぶた）の肌から取る。頬は赤みが入るので使わない
        self.lid = [sample(*e["skin"]) for e in self.eyes]
        self.inner = (104, 40, 46)
        self.tongue = (206, 112, 112)
        self.lash = (52, 34, 32)

    @staticmethod
    def _paste_rotated(img: Image.Image, patch: Image.Image, cx: float, cy: float,
                       angle: float) -> None:
        patch = patch.rotate(angle, resample=Image.BICUBIC, expand=True)
        patch = patch.filter(ImageFilter.GaussianBlur(0.8))
        img.paste(patch, (round(cx - patch.width / 2), round(cy - patch.height / 2)), patch)

    def draw(self, img: Image.Image, mouth: float, blink: float) -> None:
        m = self.mouth
        if mouth > 0.08:
            mw = m["w"]
            w = mw * (0.42 + 0.16 * mouth)
            h = mw * (0.05 + 0.22 * mouth)
            size = int(mw * 1.6)
            patch = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            d = ImageDraw.Draw(patch)
            c = size / 2
            # 唇の線を上端にして、下へ開く
            box = [c - w / 2, c - h * 0.3, c + w / 2, c + h * 0.7]
            d.ellipse(box, fill=self.inner + (255,))
            if mouth > 0.5:
                d.ellipse([c - w * 0.26, box[1] + h * 0.6, c + w * 0.26, box[3]],
                          fill=self.tongue + (255,))
            self._paste_rotated(img, patch, m["cx"], m["cy"], m.get("angle", 0))
        if blink > 0:
            for e in self.eyes:
                self._blink(img, e, blink)

    @staticmethod
    def _blink(img: Image.Image, e: dict, amount: float) -> None:
        """目を下まぶたに向かって押しつぶし、上のまぶたの肌を引き伸ばして埋める。

        上下のまつげが重なって閉じた目の線になり、元の絵の陰影もそのまま残る。
        傾いた目は、いったん水平に戻してから処理する。
        """
        cx, cy, w, h, ang = e["cx"], e["cy"], e["w"], e["h"], e.get("angle", 0)
        side = int(max(w, h) * 1.8)
        x0, y0 = round(cx - side / 2), round(cy - side / 2)
        patch = img.crop((x0, y0, x0 + side, y0 + side)).rotate(-ang, resample=Image.BICUBIC)
        c = side / 2
        left, right = int(c - w / 2 - 4), int(c + w / 2 + 4)
        top, bottom = int(c - h / 2), int(c + h / 2)
        lid_top = int(top - h * 0.3)
        eye_h = max(2, round((bottom - top) * (1 - amount)))
        cols = right - left
        skin = patch.crop((left, lid_top, right, top)).resize(
            (cols, bottom - eye_h - lid_top), Image.BICUBIC)
        eye = patch.crop((left, top, right, bottom)).resize((cols, eye_h), Image.BICUBIC)
        work = patch.copy()
        work.paste(skin, (left, lid_top))
        work.paste(eye, (left, bottom - eye_h))
        mask = Image.new("L", (side, side), 0)
        ImageDraw.Draw(mask).ellipse([left + 2, lid_top + 2, right - 2, bottom + 2], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(3))
        work = work.rotate(ang, resample=Image.BICUBIC)
        mask = mask.rotate(ang, resample=Image.BICUBIC)
        img.paste(work, (x0, y0), mask)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", nargs="?", default="script.json")
    ap.add_argument("-o", "--outdir", default="out_talk")
    ap.add_argument("--presenter", default="assets_video/presenter.png")
    ap.add_argument("--layout", default="assets_video/presenter.json")
    ap.add_argument("--host", default="http://127.0.0.1:50021")
    ap.add_argument("--speaker", type=int, default=None)
    ap.add_argument("--font", default=None)
    ap.add_argument("--preview", type=float, default=None, metavar="秒",
                    help="この秒数のフレームを1枚だけ PNG で書き出して終わる（音声合成あり）")
    args = ap.parse_args()

    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    speaker = args.speaker if args.speaker is not None else script.get("speaker", 9)
    scenes = script["scenes"]
    layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    font_path = find_font(args.font)

    base = Image.open(args.presenter).convert("RGB").resize((W, H), Image.LANCZOS)
    x0, y0, x1, y1 = layout["screen"]
    screens = [render_screen(s, (x1 - x0, y1 - y0), font_path) for s in scenes]

    outdir = Path(args.outdir)
    audio_dir = outdir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # 1. 音声（build_video.py と同じ並べ方）
    timeline: list[Path] = []
    subtitles: list[tuple[float, float, str]] = []
    scene_spans: list[tuple[float, float]] = []
    clock, n, first_wav = 0.0, 0, None
    silence: dict[float, Path] = {}
    for si, scene in enumerate(scenes):
        start = clock
        for li, line in enumerate(scene["lines"]):
            n += 1
            wav = audio_dir / f"{n:04d}.wav"
            synth(line, speaker, args.host, wav)
            first_wav = first_wav or wav
            dur = wav_duration(wav)
            timeline.append(wav)
            shown = line
            for spoken, written in script.get("caption_replace", {}).items():
                shown = shown.replace(spoken, written)
            subtitles.append((clock, clock + dur, shown))
            clock += dur
            gap = GAP_AFTER_SCENE if li == len(scene["lines"]) - 1 else GAP_AFTER_LINE
            if gap not in silence:
                silence[gap] = audio_dir / f"sil_{int(gap * 1000)}.wav"
                write_silence(silence[gap], gap, first_wav)
            timeline.append(silence[gap])
            clock += gap
        scene_spans.append((start, clock))
        print(f"  [{si + 1}/{len(scenes)}] {scene['heading']} — {clock - start:.1f}s")
    total = clock

    parts, rate = [], 24000
    for p in timeline:
        s, rate = read_wav(p)
        parts.append(s)
    samples = np.concatenate(parts)
    audio_path = outdir / "narration.wav"
    with wave.open(str(audio_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())

    n_frames = int(math.ceil(total * FPS))
    mouth = mouth_levels(samples, rate, n_frames)
    blinks = blink_schedule(n_frames)
    face = Face(base, layout)

    # シーンごとの背景（スクリーンにスライドを映した状態）
    backgrounds = []
    for scr in screens:
        bg = base.copy()
        bg.paste(scr, (x0, y0))
        backgrounds.append(bg)
    captions: dict[int, Image.Image] = {}

    def frame_at(i: int) -> Image.Image:
        t = i / FPS
        si = next((k for k, (a, b) in enumerate(scene_spans) if a <= t < b), len(scenes) - 1)
        img = backgrounds[si].copy()
        face.draw(img, float(mouth[i]) if i < len(mouth) else 0.0, blinks.get(i, 0.0))
        # ごくわずかな寄り引き（約9秒周期で最大1%）
        z = 1.005 + 0.005 * math.sin(2 * math.pi * t / 9.0)
        cw, ch = W / z, H / z
        ox = (W - cw) / 2 + 4 * math.sin(2 * math.pi * t / 13.0)
        oy = (H - ch) / 2
        img = img.transform((W, H), Image.AFFINE, (cw / W, 0, ox, 0, ch / H, oy),
                            resample=Image.BILINEAR)
        ci = next((k for k, (a, b, _) in enumerate(subtitles) if a <= t < b), None)
        if ci is not None:
            if ci not in captions:
                captions[ci] = render_caption(subtitles[ci][2], font_path)
            img.paste(captions[ci], (0, 0), captions[ci])
        return img

    if args.preview is not None:
        p = outdir / "preview.png"
        frame_at(min(int(args.preview * FPS), n_frames - 1)).save(p)
        print(f"プレビュー: {p}")
        return

    # 2. フレームを ffmpeg に直接流し込む
    mp4 = outdir / "video.mp4"
    cmd = [ffmpeg_bin(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(audio_path),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", str(mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n_frames):
        proc.stdin.write(frame_at(i).tobytes())
        if i % (FPS * 20) == 0:
            print(f"\r書き出し {i / n_frames:5.0%}", end="", flush=True)
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg が失敗しました")

    write_srt(subtitles, outdir / "video.srt")
    credit = speaker_credit(speaker, args.host)
    (outdir / "credits.txt").write_text(credit + "\n", encoding="utf-8")
    chapters = []
    for scene, (a, _) in zip(scenes, scene_spans):
        m, s = divmod(int(a), 60)
        chapters.append(f"{m:02d}:{s:02d} {scene['heading']}")
    (outdir / "chapters.txt").write_text("\n".join(chapters) + "\n", encoding="utf-8")

    mins, secs = divmod(total, 60)
    print(f"\r完成: {mp4}")
    print(f"クレジット: {credit}")
    print(f"尺: {int(mins)}分{secs:04.1f}秒 / シーン {len(scenes)}")


if __name__ == "__main__":
    main()

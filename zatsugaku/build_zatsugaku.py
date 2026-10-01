#!/usr/bin/env python3
"""雑学動画（白背景＋上に大きな文字＋いらすとや＋ナレーション＋BGM）を書き出す。

    python3 build_zatsugaku.py scripts/trial_01.json -o out/trial_01

音声エンジン:
    GEMINI_API_KEY があれば Gemini の音声生成を使う（--engine gemini で強制）。
    無ければ VOICEVOX（既定 http://127.0.0.1:50021）を使う。

BGM は assets/bgm/escort.mp3（もっぴーさうんど「Escort」／OpenTracks 旧DOVA-SYNDROME）を
曲の長さが足りない分だけ繰り返して敷き、最後をフェードアウトする。
字幕とスライドの切り替えは、合成した音声の実長から積み上げる。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
IMG_DIR = HERE / "assets" / "irasutoya"
BGM = HERE / "assets" / "bgm" / "escort.mp3"

W, H = 1920, 1080
BG = (255, 255, 255)
INK = (17, 17, 17)
SUB = (120, 120, 120)

HIRAGINO_BOLD = Path("/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc")
HIRAGINO_REG = Path("/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc")
NOTO = HERE / "assets" / "fonts" / "NotoSansJP.ttf"  # Mac 以外（クラウド）用。fetch_assets.py が取る

GAP_AFTER_LINE = 0.25
GAP_AFTER_ITEM = 0.6
BGM_VOLUME = 0.13
SAMPLE_RATE = 24000

VOICEVOX = os.environ.get("VOICEVOX_HOST", "http://127.0.0.1:50021")
VOICEVOX_SPEED = float(os.environ.get("VOICEVOX_SPEED", "1.15"))
GEMINI_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
GEMINI_STYLE = "落ち着いた男性の声で、雑学を紹介するナレーターとして、はっきり自然に読み上げてください: "



def find_ffmpeg() -> str:
    for p in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg"):
        if p and Path(p).exists():
            return p
    import imageio_ffmpeg  # クラウドは cloud/setup.sh が入れる
    return imageio_ffmpeg.get_ffmpeg_exe()


FFMPEG = find_ffmpeg()


def font(size: int, bold: bool) -> ImageFont.FreeTypeFont:
    path = HIRAGINO_BOLD if bold else HIRAGINO_REG
    if path.exists():
        return ImageFont.truetype(str(path), size)
    f = ImageFont.truetype(str(NOTO), size)  # 可変フォント。太さを名前で選ぶ
    f.set_variation_by_name("Black" if bold else "Regular")
    return f


# --- 音声 -----------------------------------------------------------------

def tts_voicevox(text: str, speaker: int, path: Path) -> None:
    q = urllib.parse.urlencode({"text": text, "speaker": speaker})
    req = urllib.request.Request(f"{VOICEVOX}/audio_query?{q}", method="POST")
    query = json.load(urllib.request.urlopen(req, timeout=60))
    query["speedScale"] = VOICEVOX_SPEED
    query["outputSamplingRate"] = SAMPLE_RATE
    query["prePhonemeLength"] = 0.05
    query["postPhonemeLength"] = 0.05
    req = urllib.request.Request(
        f"{VOICEVOX}/synthesis?speaker={speaker}",
        data=json.dumps(query).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    path.write_bytes(urllib.request.urlopen(req, timeout=120).read())


def tts_gemini(text: str, voice: str, path: Path) -> None:
    key = os.environ["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": GEMINI_STYLE + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    for attempt in range(6):
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST",
        )
        try:
            d = json.load(urllib.request.urlopen(req, timeout=120))
            pcm = base64.b64decode(d["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < 5:
                time.sleep(15 * (attempt + 1))
                continue
            sys.exit(f"Gemini 音声生成に失敗: {e.code} {e.read()[:300]!r}")
    with wave.open(str(path), "wb") as w:  # Gemini は 24kHz/16bit/モノラルの生PCMを返す
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


# --- 画面 -----------------------------------------------------------------

def fit_caption(draw: ImageDraw.ImageDraw, text: str) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    lines = text.split("\n")
    for size in range(118, 50, -4):
        f = font(size, bold=True)
        if all(draw.textlength(l, font=f) <= W - 160 for l in lines) and size * 1.25 * len(lines) <= 330:
            return f, lines
    return font(50, bold=True), lines


def render_slide(caption: str, image: str, source: str | None, path: Path) -> None:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    cf, lines = fit_caption(d, caption)
    lh = int(cf.size * 1.25)
    y = 60 + (330 - lh * len(lines)) // 2
    for l in lines:
        tw = d.textlength(l, font=cf)
        d.text(((W - tw) / 2, y), l, font=cf, fill=INK)
        y += lh

    pic = Image.open(IMG_DIR / image).convert("RGBA")
    box_w, box_h = 1100, 600 if source else 640
    pic.thumbnail((box_w, box_h), Image.LANCZOS)
    if pic.width < box_w and pic.height < box_h:  # 小さい絵は拡大して面積をそろえる
        r = min(box_w / pic.width, box_h / pic.height)
        pic = pic.resize((int(pic.width * r), int(pic.height * r)), Image.LANCZOS)
    top = 410
    im.paste(pic, ((W - pic.width) // 2, top + (box_h - pic.height) // 2), pic)

    if source:
        sf = font(30, bold=False)
        s = "出典：" + source
        d.text(((W - d.textlength(s, font=sf)) / 2, H - 62), s, font=sf, fill=SUB)

    im.save(path)


# --- 組み立て -------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--engine", choices=["auto", "gemini", "voicevox"], default="auto")
    args = ap.parse_args()

    sc = json.loads(Path(args.script).read_text(encoding="utf-8"))
    subprocess.run([sys.executable, str(HERE / "fetch_assets.py")], check=True)
    out = Path(args.out)
    (out / "slides").mkdir(parents=True, exist_ok=True)
    (out / "voice").mkdir(parents=True, exist_ok=True)

    engine = args.engine
    if engine == "auto":
        engine = "gemini" if os.environ.get("GEMINI_API_KEY") else "voicevox"
    print(f"音声エンジン: {engine}")

    images = {it["image"] for it in sc["items"]}
    if len(images) > 20:
        sys.exit(f"いらすとやは1作品20点までです（{len(images)}点）")

    concat_v, concat_a, srt = [], [], []
    t = 0.0
    n = 0
    silence = {}

    def silent(sec: float) -> Path:
        if sec not in silence:
            p = out / "voice" / f"silence_{int(sec*1000)}.wav"
            with wave.open(str(p), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
                w.writeframes(b"\0\0" * int(SAMPLE_RATE * sec))
            silence[sec] = p
        return silence[sec]

    for ii, item in enumerate(sc["items"]):
        for li, line in enumerate(item["lines"]):
            n += 1
            wav = out / "voice" / f"{n:03d}.wav"
            if not wav.exists():
                if engine == "gemini":
                    tts_gemini(line["say"], sc.get("gemini_voice", "Charon"), wav)
                else:
                    tts_voicevox(line["say"], sc.get("speaker", 13), wav)
            last_in_item = li == len(item["lines"]) - 1
            gap = GAP_AFTER_ITEM if last_in_item else GAP_AFTER_LINE
            dur = wav_seconds(wav) + gap
            png = out / "slides" / f"{n:03d}.png"
            render_slide(line["caption"], item["image"], item.get("source"), png)
            concat_v.append(f"file '{png.resolve()}'\nduration {dur:.3f}")
            concat_a += [f"file '{wav.resolve()}'", f"file '{silent(gap).resolve()}'"]
            srt.append((t, t + dur - gap, line["caption"].replace("\n", "")))
            t += dur
            print(f"  {n:03d} {dur:5.2f}s  {line['caption'].replace(chr(10), ' ')}")

    concat_v.append(f"file '{(out / 'slides' / f'{n:03d}.png').resolve()}'")  # concat の仕様で最後をもう一度
    (out / "video.txt").write_text("\n".join(concat_v) + "\n")
    (out / "audio.txt").write_text("\n".join(concat_a) + "\n")

    def ts(x: float) -> str:
        h, r = divmod(x, 3600); m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")
    (out / "video.srt").write_text(
        "".join(f"{i}\n{ts(a)} --> {ts(b)}\n{c}\n\n" for i, (a, b, c) in enumerate(srt, 1)), encoding="utf-8")

    total = t
    fade = 3.0
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(out / "audio.txt"),
                    "-c:a", "pcm_s16le", str(out / "narration.wav")], check=True)
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(out / "video.txt"),
        "-i", str(out / "narration.wav"),
        "-stream_loop", "-1", "-i", str(BGM),
        "-filter_complex",
        f"[2:a]volume={BGM_VOLUME},atrim=0:{total:.3f},afade=t=out:st={total - fade:.3f}:d={fade}[bgm];"
        f"[1:a]aresample=48000[nar];[nar][bgm]amix=inputs=2:duration=first:normalize=0,"
        f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]",  # YouTube の基準音量にそろえる
        "-map", "0:v", "-map", "[a]",
        "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart",
        str(out / "video.mp4"),
    ], check=True)

    # upload_youtube.py は credits.txt を「■ 音声」として概要欄に入れる。BGM と絵は概要欄本文に書く。
    voice = "Gemini 音声生成（Google）" if engine == "gemini" else "VOICEVOX:青山龍星"
    (out / "credits.txt").write_text(voice + "\n", encoding="utf-8")

    (out / "meta.json").write_text(json.dumps({"duration": round(total, 2), "slides": n,
                                               "images": len(images)}), encoding="utf-8")
    yt = dict(sc.get("youtube", {}))
    yt["synthetic"] = True  # 合成音声を使っていることを申告する（記事動画のルーティンと同じ）
    desc = [yt.get("description", "").strip()]
    if yt.get("sources"):
        desc.append("■ 出典\n" + "\n".join(f"・{s}" for s in yt["sources"]))
    desc.append("※この動画は一般的な健康情報の紹介です。医師による診断・治療に代わるものではありません。"
                "持病のある方は、食事や運動を変える前にかかりつけ医にご相談ください。")
    if any(it.get("category") in ("投資", "資産管理") for it in sc["items"]):
        desc.append("※お金に関する内容は一般的な情報の紹介です。特定の金融商品を勧めるものではありません。"
                    "投資の判断はご自身の責任で行ってください。")
    desc.append("■ BGM\n「Escort」もっぴーさうんど（フリーBGM OpenTracks 旧DOVA-SYNDROME）\n■ イラスト\nいらすとや")
    desc.append("■ 田園生活ブログ\nhttps://denenseikatu.com/")
    yt["description"] = "\n\n".join(d for d in desc if d)
    (out / "upload.json").write_text(json.dumps({"youtube": yt}, ensure_ascii=False, indent=2), encoding="utf-8")
    m, s = divmod(total, 60)
    print(f"完了: {out / 'video.mp4'}  尺 {int(m)}分{s:04.1f}秒  画面 {n}枚  絵 {len(images)}点")


if __name__ == "__main__":
    main()

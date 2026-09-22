#!/usr/bin/env python3
"""script.json から mp4 と srt を書き出す。

    # VOICEVOX を起動した状態で
    python3 build_video.py script.json -o out/

    # スライドだけ確認する（VOICEVOX 不要）
    python3 build_video.py script.json -o out/ --slides-only

音声は VOICEVOX ENGINE (既定 http://127.0.0.1:50021) で合成する。
字幕のタイムコードは、推定ではなく合成した wav の実長から組み立てる。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BG = (247, 244, 238)
INK = (31, 28, 26)
SUB = (104, 96, 88)
ACCENT = (183, 40, 46)  # 鳥居の朱

GAP_AFTER_LINE = 0.35   # 文と文のあいだ（秒）
GAP_AFTER_SCENE = 0.65  # スライドの切り替わり（秒）

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]

# 決め打ちで当たらなかったときに探すディレクトリとファイル名パターン。
# macOS はヒラギノの場所がOSバージョンで変わるため、名前で拾う。
FONT_DIRS = [
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
    "~/Library/Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "C:/Windows/Fonts",
]
FONT_GLOBS = [
    "ヒラギノ角ゴ*.ttc", "ヒラギノ角ゴ*.otf", "ヒラギノ*.ttc",
    "Hiragino*.ttc", "Hiragino*.otf",
    "YuGoth*.ttc", "YuGo*.otf", "meiryo*.ttc", "msgothic.ttc",
    "NotoSansCJK*", "NotoSansJP*", "ipag*.ttf", "fonts-japanese-gothic.ttf",
]


def find_font(explicit: str | None = None) -> str:
    if explicit:
        if not Path(explicit).is_file():
            sys.exit(f"指定されたフォントがありません: {explicit}")
        return explicit

    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return path

    for d in FONT_DIRS:
        base = Path(d).expanduser()
        if not base.is_dir():
            continue
        for pattern in FONT_GLOBS:
            # フォントはサブディレクトリに置かれることが多いので再帰で探す
            # （例: /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf）
            hits = sorted(base.rglob(pattern))
            if hits:
                return str(hits[0])

    searched = "\n  ".join(FONT_DIRS)
    sys.exit(
        "日本語フォントが見つかりません。探した場所:\n  " + searched + "\n"
        "--font でフォントファイルを直接指定してください。\n"
        "例: --font '/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc'"
    )


def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg が見つかりません。`pip install imageio-ffmpeg` でも代用できます。")


# ---------------------------------------------------------------- スライド描画


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """日本語は単語境界が無いので、幅を測りながら1文字ずつ折り返す。"""
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        if draw.textlength(trial, font=font) > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


NARRATOR_SIZE = 260       # 立ち絵の直径
NARRATOR_MARGIN = 70      # 右下からの余白


def paste_narrator(img: Image.Image, narrator_path: Path) -> None:
    """語り手の立ち絵を右下に円形で置く。素材は正方形でなくてもよい。"""
    try:
        src = Image.open(narrator_path).convert("RGB")
    except Exception:
        return

    # 中央を正方形に切り出してから縮小する（顔が入るよう上寄りに取る）
    w, h = src.size
    side = min(w, h)
    left = (w - side) // 2
    top = int((h - side) * 0.25)
    src = src.crop((left, top, left + side, top + side)).resize(
        (NARRATOR_SIZE, NARRATOR_SIZE), Image.LANCZOS
    )

    mask = Image.new("L", (NARRATOR_SIZE, NARRATOR_SIZE), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, NARRATOR_SIZE - 1, NARRATOR_SIZE - 1], fill=255)

    x = W - NARRATOR_SIZE - NARRATOR_MARGIN
    y = H - NARRATOR_SIZE - NARRATOR_MARGIN
    # 縁取り
    ImageDraw.Draw(img).ellipse(
        [x - 5, y - 5, x + NARRATOR_SIZE + 4, y + NARRATOR_SIZE + 4], fill=ACCENT
    )
    img.paste(src, (x, y), mask)


def draw_slide(
    scene: dict,
    font_path: str,
    is_title: bool,
    footer: str,
    out_path: Path,
    narrator: Path | None = None,
) -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # 上辺の朱線
    d.rectangle([0, 0, W, 12], fill=ACCENT)

    if is_title:
        f_title = ImageFont.truetype(font_path, 104)
        f_sub = ImageFont.truetype(font_path, 46)
        title_lines = wrap(d, scene["heading"], f_title, W - 320)
        total = len(title_lines) * 130
        y = (H - total) // 2 - 60
        for ln in title_lines:
            tw = d.textlength(ln, font=f_title)
            d.text(((W - tw) / 2, y), ln, font=f_title, fill=INK)
            y += 130
        d.rectangle([(W - 160) / 2, y + 24, (W + 160) / 2, y + 30], fill=ACCENT)
        y += 80
        for b in scene.get("bullets", []):
            tw = d.textlength(b, font=f_sub)
            d.text(((W - tw) / 2, y), b, font=f_sub, fill=SUB)
            y += 70
    else:
        f_head = ImageFont.truetype(font_path, 74)
        f_body = ImageFont.truetype(font_path, 52)
        x = 180
        y = 200
        for ln in wrap(d, scene["heading"], f_head, W - 360):
            d.text((x, y), ln, font=f_head, fill=INK)
            y += 96
        d.rectangle([x, y + 18, x + 120, y + 24], fill=ACCENT)
        y += 110

        for b in scene.get("bullets", []):
            d.ellipse([x + 6, y + 22, x + 24, y + 40], fill=ACCENT)
            bx = x + 56
            for i, ln in enumerate(wrap(d, b, f_body, W - 360 - 56)):
                d.text((bx, y), ln, font=f_body, fill=INK if i == 0 else SUB)
                y += 68
            y += 22

    if footer:
        f_foot = ImageFont.truetype(font_path, 30)
        d.text((180, H - 90), footer, font=f_foot, fill=SUB)

    if narrator and narrator.is_file():
        paste_narrator(img, narrator)

    img.save(out_path)


# ---------------------------------------------------------------- 音声合成


def synth(text: str, speaker: int, host: str, out_path: Path) -> None:
    q = urllib.parse.urlencode({"text": text, "speaker": speaker})
    req = urllib.request.Request(f"{host}/audio_query?{q}", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            query = r.read()
    except Exception as e:
        sys.exit(f"VOICEVOX に接続できません ({host}): {e}\nVOICEVOX ENGINE を起動してください。")

    req = urllib.request.Request(
        f"{host}/synthesis?speaker={speaker}",
        data=query,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        out_path.write_bytes(r.read())


# Open JTalk が使う HTS 音声「Mei」は CC BY 3.0 で、表示が義務。
OPENJTALK_CREDIT = (
    'Open JTalk / HTS Voice "Mei" '
    "(MMDAgent Project Team, 名古屋工業大学) CC BY 3.0"
)


def synth_openjtalk(text: str, out_path: Path) -> None:
    """VOICEVOX が使えない環境向けのローカル合成。声質は素朴だが外部接続が要らない。"""
    try:
        import numpy as np
        import pyopenjtalk
    except ImportError:
        sys.exit("pyopenjtalk が必要です。`pip install pyopenjtalk numpy` を実行してください。")

    x, sr = pyopenjtalk.tts(text)
    pcm = (np.clip(x / 32768.0, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())


def engine_brand(host: str) -> str:
    """エンジンの製品名。VOICEVOX 互換エンジン（AivisSpeech など）もあるため、
    製品名を決め打ちせずマニフェストから取る。"""
    try:
        with urllib.request.urlopen(f"{host}/engine_manifest", timeout=30) as r:
            manifest = json.loads(r.read())
        return manifest.get("brand_name") or manifest.get("name") or "VOICEVOX"
    except Exception:
        return "VOICEVOX"


def speaker_credit(speaker: int, host: str) -> str:
    """利用規約はキャラクター名の表記を求めるので、エンジンから正式名称を
    引いてクレジット文字列を作る（推測で書かない）。"""
    brand = engine_brand(host)
    try:
        with urllib.request.urlopen(f"{host}/speakers", timeout=30) as r:
            speakers = json.loads(r.read())
    except Exception:
        return brand
    for sp in speakers:
        for style in sp.get("styles", []):
            if style.get("id") == speaker:
                return f"{brand}:{sp['name']}"
    return brand


def wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def write_silence(path: Path, seconds: float, like: Path) -> None:
    with wave.open(str(like)) as w:
        params = w.getparams()
    frames = int(params.framerate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        w.writeframes(b"\x00" * frames * params.nchannels * params.sampwidth)


# ---------------------------------------------------------------- 字幕


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(entries: list[tuple[float, float, str]], path: Path) -> None:
    out = []
    for i, (start, end, text) in enumerate(entries, 1):
        out.append(f"{i}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n")
    path.write_text("\n".join(out), encoding="utf-8")


# ---------------------------------------------------------------- 本体


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("script", nargs="?", default="script.json")
    ap.add_argument("-o", "--outdir", default="out")
    ap.add_argument("--host", default="http://127.0.0.1:50021", help="VOICEVOX ENGINE の URL")
    ap.add_argument("--speaker", type=int, default=None, help="script.json の話者IDを上書き")
    ap.add_argument("--slides-only", action="store_true", help="スライドPNGだけ出す（VOICEVOX 不要）")
    ap.add_argument("--font", default=None, help="日本語フォントを直接指定する")
    ap.add_argument("--narrator", default="assets_video/narrator.png",
                    help="スライド右下に置く語り手の画像。無ければ置かない")
    ap.add_argument("--engine", choices=["voicevox", "openjtalk"], default="voicevox",
                    help="音声合成の方式。openjtalk はローカル完結だが声質は素朴")
    args = ap.parse_args()

    script_path = Path(args.script)
    if not script_path.is_file():
        sys.exit(
            f"台本がありません: {script_path}\n"
            "prompts/narration.md のルールに従って、対象記事から台本を作ってください。\n"
            "書式の見本: examples/script.sample.json\n"
            "（見本は神社記事のものです。そのまま書き出さないでください）"
        )
    script = json.loads(script_path.read_text(encoding="utf-8"))
    speaker = args.speaker if args.speaker is not None else script.get("speaker", 10)
    scenes = script["scenes"]

    outdir = Path(args.outdir)
    slides_dir = outdir / "slides"
    audio_dir = outdir / "audio"
    slides_dir.mkdir(parents=True, exist_ok=True)
    font_path = find_font(args.font)

    narrator = Path(args.narrator).expanduser() if args.narrator else None
    if narrator and not narrator.is_file():
        print(f"語り手の画像が無いので置きません: {narrator}")
        narrator = None

    # 1. スライド（フッターは台本の出典から。ドメインを決め打ちしない）
    footer = script.get("site_host") or urllib.parse.urlparse(
        script.get("source_url", "")
    ).netloc
    slide_paths = []
    for i, scene in enumerate(scenes):
        p = slides_dir / f"{i + 1:02d}.png"
        draw_slide(scene, font_path, is_title=(i == 0), footer=footer, out_path=p,
                   narrator=narrator)
        slide_paths.append(p)
    print(f"スライド {len(slide_paths)} 枚 → {slides_dir}")

    if args.slides_only:
        print("--slides-only のため、音声合成と動画書き出しは行いません。")
        return

    # 2. 音声合成（1行 = 1ファイル）と、無音を挟んだ再生順の組み立て
    audio_dir.mkdir(parents=True, exist_ok=True)
    timeline: list[Path] = []          # 連結する wav の順番
    subtitles: list[tuple[float, float, str]] = []
    slide_durations: list[float] = []
    clock = 0.0
    silence_cache: dict[float, Path] = {}
    first_wav: Path | None = None

    n = 0
    for si, scene in enumerate(scenes):
        scene_start = clock
        lines = scene["lines"]
        for li, line in enumerate(lines):
            n += 1
            wav = audio_dir / f"{n:04d}.wav"
            if args.engine == "openjtalk":
                synth_openjtalk(line, wav)
            else:
                synth(line, speaker, args.host, wav)
            first_wav = first_wav or wav
            dur = wav_duration(wav)
            timeline.append(wav)
            subtitles.append((clock, clock + dur, line))
            clock += dur

            gap = GAP_AFTER_SCENE if li == len(lines) - 1 else GAP_AFTER_LINE
            if gap not in silence_cache:
                sp = audio_dir / f"sil_{int(gap * 1000)}.wav"
                write_silence(sp, gap, first_wav)
                silence_cache[gap] = sp
            timeline.append(silence_cache[gap])
            clock += gap

        slide_durations.append(clock - scene_start)
        print(f"  [{si + 1}/{len(scenes)}] {scene['heading']} — {clock - scene_start:.1f}s")

    total = clock

    # 3. 字幕
    srt_path = outdir / "video.srt"
    write_srt(subtitles, srt_path)

    # 4. ffmpeg で連結
    audio_list = outdir / "audio.txt"
    audio_list.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in timeline), encoding="utf-8"
    )
    image_list = outdir / "images.txt"
    lines_txt = []
    for p, d in zip(slide_paths, slide_durations):
        lines_txt.append(f"file '{p.resolve().as_posix()}'\nduration {d:.3f}\n")
    lines_txt.append(f"file '{slide_paths[-1].resolve().as_posix()}'\n")  # concat の作法
    image_list.write_text("".join(lines_txt), encoding="utf-8")

    mp4 = outdir / "video.mp4"
    cmd = [
        ffmpeg_bin(), "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(image_list),
        "-f", "concat", "-safe", "0", "-i", str(audio_list),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k",
        # concat の末尾で最終画像を再掲する作法が余分な尺を生み、-shortest では
        # 切り落とせないことがある。音声タイムラインの長さを明示して確実に揃える。
        "-t", f"{total:.3f}",
        str(mp4),
    ]
    subprocess.run(cmd, check=True)

    # 5. アップロード用の付随情報（実測タイムから作る）
    credit = (
        OPENJTALK_CREDIT if args.engine == "openjtalk"
        else speaker_credit(speaker, args.host)
    )
    (outdir / "credits.txt").write_text(credit + "\n", encoding="utf-8")

    chapters, at = [], 0.0
    for scene, dur in zip(scenes, slide_durations):
        m, s = divmod(int(at), 60)
        chapters.append(f"{m:02d}:{s:02d} {scene['heading']}")
        at += dur
    (outdir / "chapters.txt").write_text("\n".join(chapters) + "\n", encoding="utf-8")

    mins, secs = divmod(total, 60)
    print(f"\n完成: {mp4}")
    print(f"字幕: {srt_path}（{len(subtitles)} 枚）")
    print(f"クレジット: {credit}")
    print(f"尺: {int(mins)}分{secs:04.1f}秒 / スライド {len(slide_paths)} 枚")


if __name__ == "__main__":
    main()

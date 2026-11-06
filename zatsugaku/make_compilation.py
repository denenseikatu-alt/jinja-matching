#!/usr/bin/env python3
"""これまでの雑学動画をつないで、1本の長い動画（聞き流し用のまとめ）を作る。

    python3 make_compilation.py <記録先> <記録先> ... -o out/compilation-2026-10 [--title ...]

- 各回の台本（scripts/<記録先>.json）から動画を作る。out/<記録先>/video.mp4 があればそれを使う
  （作り直すときは、台本の決まりで変わった言葉＝「育つ」→「発達する」などを直した写しから作る）
- 各回の締め（「いくつ知っていましたか」〜「チャンネル登録」の3枚）は、最後の回以外は切る
- つなぎ目は音を短く絞って、BGM が急に切り替わらないようにする
- 最初に題名の画面を入れ、概要欄に各回の目次（時刻つき）を書く
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from build_video import ffmpeg_bin, find_font  # noqa: E402

FIX = {"育つ": "発達する", "重い重さ": "高重量"}
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30",
       "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("失敗しました:\n" + " ".join(cmd[:6]) + "\n" + r.stderr[-1500:])


def duration(ff: str, path: Path) -> float:
    r = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def ensure_video(key: str) -> Path:
    out = HERE / "out" / key
    video = out / "video.mp4"
    if video.exists():
        return video
    sc = json.loads((HERE / "scripts" / f"{key}.json").read_text(encoding="utf-8"))
    txt = json.dumps(sc, ensure_ascii=False)
    for a, b in FIX.items():
        txt = txt.replace(a, b)
    sc = json.loads(txt)
    # 古い台本は絵のファイル名だけが書いてあり、手元に絵がないことがある。その絵は取り直す
    img_dir = HERE / "assets" / "irasutoya"
    for it in sc["items"]:
        img = it.get("image")
        if img and img not in ("hirameki_man.png", "uroko_man.png") and not (img_dir / img).exists():
            it.pop("image")
            first = it["lines"][0]["caption"].split("\n")[0] if it.get("lines") else ""
            it.setdefault("image_query", it.get("topic") or re.sub(r"[？?！!、。]", "", first)[:12])
    txt = json.dumps(sc, ensure_ascii=False)
    fixed = HERE / "out" / f"{key}.fixed.json"
    fixed.parent.mkdir(parents=True, exist_ok=True)
    fixed.write_text(txt, encoding="utf-8")
    run([sys.executable, str(HERE / "fetch_irasutoya.py"), str(fixed)])
    run([sys.executable, str(HERE / "build_zatsugaku.py"), str(fixed), "-o", str(out), "--engine", "voicevox"])
    print(f"作り直しました: {key}（{duration(ffmpeg_bin(), video):.0f}秒）", flush=True)
    return video


def outro_seconds(key: str) -> float:
    """最後の3枚（締め）の長さ。video.txt（各画面の表示時間）から読む。"""
    durs = [float(x) for x in re.findall(r"^duration ([\d.]+)", (HERE / "out" / key / "video.txt")
                                         .read_text(encoding="utf-8"), re.M)]
    return sum(durs[-3:])


def title_card(lines: list[str], path: Path, font_path: str) -> None:
    im = Image.new("RGB", (1920, 1080), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1920, 120], fill=(27, 54, 93))
    d.rectangle([0, 960, 1920, 1080], fill=(27, 54, 93))
    for i, (ln, size) in enumerate(lines):
        f = ImageFont.truetype(font_path, size)
        d.text((960, 380 + i * 170), ln, font=f, anchor="mm", fill=(31, 28, 26))
    d.text((960, 1020), "田園生活", font=ImageFont.truetype(font_path, 44), anchor="mm", fill=(255, 255, 255))
    im.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("keys", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--title", default="【聞き流し】9割が知らない健康と体づくりの雑学 一気見｜全部、論文で確認済み")
    a = ap.parse_args()
    ff, font_path = ffmpeg_bin(), find_font(None)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    state = json.loads((HERE / "state.json").read_text(encoding="utf-8"))
    chapters, clock = [], 0.0
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        parts = []
        card = t / "title.png"
        n = len(a.keys)
        title_card([("9割が知らない雑学", 120), (f"{n}本 一気見", 110), ("全部、研究論文で確かめました", 64)],
                   card, font_path)
        seg = t / "p000.mp4"
        run([ff, "-y", "-loop", "1", "-t", "6", "-i", str(card), "-f", "lavfi", "-t", "6",
             "-i", "anullsrc=r=48000:cl=stereo", "-shortest", *ENC, str(seg)])
        parts.append(seg)
        clock = 6.0
        for i, key in enumerate(a.keys):
            video = ensure_video(key)
            total = duration(ff, video)
            keep = total if i == n - 1 else total - outro_seconds(key)
            seg = t / f"p{i + 1:03d}.mp4"
            run([ff, "-y", "-i", str(video), "-t", f"{keep:.3f}",
                 "-af", f"afade=t=in:d=0.3,afade=t=out:st={max(0, keep - 0.8):.3f}:d=0.8", *ENC, str(seg)])
            parts.append(seg)
            title = (state["done"].get(key, {}).get("title") or key)
            for x, y in FIX.items():
                title = title.replace(x, y)
            title = re.sub(r"^9割が(知らない|信じてる)", "", title).strip()
            m, s = divmod(int(clock), 60)
            h, m = divmod(m, 60)
            chapters.append((f"{h}:{m:02d}:{s:02d}", title))
            clock += duration(ff, seg)
            print(f"[{i + 1}/{n}] {key} {keep:.0f}秒（合計 {clock / 60:.1f}分）", flush=True)
        lst = t / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart",
             str(out / "video.mp4")])
    total = duration(ff, out / "video.mp4")
    toc = "\n".join(f"{ts} {ttl}" for ts, ttl in chapters)
    desc = (f"これまでに公開した「9割が知らない」雑学動画{n}本を、1本にまとめました（約{total / 3600:.1f}時間）。"
            "体づくり・栄養・健康・暮らし・猫の気持ちまで、すべて研究論文の要旨で確かめた雑学です。"
            "作業中や寝る前の聞き流しにどうぞ。\n\n"
            f"■ 目次\n0:00:00 はじめに\n{toc}\n\n"
            "■ 出典\n各回の出典は、それぞれの回の動画の概要欄にまとめています。\n"
            "▶ 9割が知らない体づくりの雑学（再生リスト）: https://www.youtube.com/playlist?list=PLGyGHovt9baI\n"
            "▶ 地域猫クロちゃんと旅先の猫たちの動画: https://www.youtube.com/playlist?list=PLF-K4PjwF37w\n\n"
            "※本動画は一般的な健康情報の紹介であり、医師の診断・治療に代わるものではありません。\n\n"
            "■ BGM\n「Escort」もっぴーさうんど（フリーBGM OpenTracks 旧DOVA-SYNDROME）")
    (out / "upload.json").write_text(json.dumps({"youtube": {
        "title": a.title, "description": desc,
        "tags": ["雑学", "聞き流し", "作業用", "健康", "筋トレ", "栄養", "睡眠", "猫", "豆知識"],
        "categoryId": "27", "privacyStatus": "public"}}, ensure_ascii=False, indent=1), encoding="utf-8")
    credit = (HERE / "out" / a.keys[0] / "credits.txt").read_text(encoding="utf-8")
    (out / "credits.txt").write_text(credit, encoding="utf-8")
    print(f"完成: {out / 'video.mp4'}（{total / 60:.1f}分・{n}本）")


if __name__ == "__main__":
    main()

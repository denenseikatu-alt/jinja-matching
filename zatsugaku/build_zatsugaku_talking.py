#!/usr/bin/env python3
"""雑学動画を、記事動画と同じ形式（アニメ調の語り手がスクリーンの横で話す・声は Gemini Leda）で書き出す。
BGM だけは雑学動画の「Escort」を敷く（2026-10-16 オーナー指示）。

    python3 build_zatsugaku_talking.py scripts/<記録先>.json -o out/<記録先>

台本は今までの雑学の台本（items / lines の caption・say）のまま。ここで記事動画の台本（scenes）に組み替えて
../build_talking.py で書き出し、BGM を重ねる。出力は build_zatsugaku.py と同じ
（video.mp4・upload.json・credits.txt・meta.json）なので、アップロード以降の手順は変わらない。
GEMINI_API_KEY が必要。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from build_zatsugaku import BGM, BGM_VOLUME, FFMPEG, make_bgm_bed  # noqa: E402

# 記事動画と同じ声（見本 talk/40s-safe-aerobic-talking.json）。style は英語のまま変えない
VOICE = {"engine": "gemini", "name": "Leda",
         "style": "Say in a bright, friendly young woman's voice, at a natural, lively conversational pace"}


def flat(caption: str) -> str:
    return re.sub(r"\s*\n\s*", "", caption).strip()


def to_talking(sc: dict) -> dict:
    """雑学の台本 → 記事動画の台本（1個の雑学 = 1場面）。"""
    items = sc["items"]
    scenes = []
    intro, *body, outro = items
    scenes.append({"heading": sc.get("title", "").replace("9割が知らない ", "9割が知らない"),
                   "bullets": [flat(ln["caption"]) for ln in intro["lines"][1:]],
                   "lines": [ln["say"] for ln in intro["lines"]]})
    for k, it in enumerate(body, 1):
        caps = [flat(ln["caption"]) for ln in it["lines"]]
        bullets = caps[1:]
        if it.get("source"):
            bullets.append(f"出典：{it['source']}")
        scenes.append({"heading": f"{k}. {caps[0]}", "bullets": bullets[:5],
                       "lines": [ln["say"] for ln in it["lines"]]})
    scenes.append({"heading": flat(outro["lines"][0]["caption"]),
                   "bullets": [flat(ln["caption"]) for ln in outro["lines"][1:]],
                   "lines": [ln["say"] for ln in outro["lines"]]})
    return {"title": sc.get("title", ""), "voice": VOICE, "scenes": scenes}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    sc = json.loads(Path(a.script).read_text(encoding="utf-8"))
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    talk = to_talking(sc)
    tpath = out / "talking.json"
    tpath.write_text(json.dumps(talk, ensure_ascii=False, indent=2), encoding="utf-8")

    # 1. 記事動画と同じ書き出し（語り手・ポーズ・口の動き・字幕）。声だけの動画ができる
    r = subprocess.run([sys.executable, str(REPO / "build_talking.py"), str(tpath), "-o", str(out / "talk")],
                       cwd=REPO)
    if r.returncode:
        sys.exit("語り手の動画の書き出しに失敗しました")
    talk_mp4 = out / "talk" / "video.mp4"
    probe = subprocess.run([FFMPEG, "-hide_banner", "-i", str(talk_mp4)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe).groups()
    total = int(h) * 3600 + int(m) * 60 + float(s)

    # 2. 雑学動画の BGM（Escort）を、声の下に小さく敷く
    make_bgm_bed(total, out / "bgm_bed.wav")
    fade = 2.0
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error", "-i", str(talk_mp4), "-i", str(out / "bgm_bed.wav"),
        "-filter_complex",
        f"[1:a]volume={BGM_VOLUME},atrim=0:{total:.3f},afade=t=out:st={max(0, total - fade):.3f}:d={fade}[bgm];"
        f"[0:a]aresample=48000[nar];[nar][bgm]amix=inputs=2:duration=first:normalize=0[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(out / "video.mp4")], check=True)

    # 3. アップロード用の情報（build_zatsugaku.py と同じ形。絵は使わないので、いらすとやの表記は外す）
    credit = (out / "talk" / "credits.txt").read_text(encoding="utf-8").strip()
    (out / "credits.txt").write_text(credit + "\n", encoding="utf-8")
    (out / "meta.json").write_text(json.dumps({"duration": round(total, 2), "slides": len(talk["scenes"]),
                                               "style": "talking"}), encoding="utf-8")
    yt = dict(sc.get("youtube", {}))
    yt["synthetic"] = True
    desc = [yt.get("description", "").strip()]
    if yt.get("sources"):
        desc.append("■ 出典\n" + "\n".join(f"・{s}" for s in yt["sources"]))
    desc.append("※この動画は一般的な健康情報の紹介です。医師による診断・治療に代わるものではありません。"
                "持病のある方は、食事や運動を変える前にかかりつけ医にご相談ください。")
    desc.append("※この動画の音声は、AI で生成したものです。")
    desc.append("■ BGM\n「Escort」もっぴーさうんど（フリーBGM OpenTracks 旧DOVA-SYNDROME）")
    desc.append("■ 田園生活ブログ\nhttps://denenseikatu.com/")
    yt["description"] = "\n\n".join(d for d in desc if d)
    (out / "upload.json").write_text(json.dumps({"youtube": yt}, ensure_ascii=False, indent=2), encoding="utf-8")
    mm, ss = divmod(total, 60)
    print(f"完了: {out / 'video.mp4'}  尺 {int(mm)}分{ss:04.1f}秒  場面 {len(talk['scenes'])}  BGM {BGM.name}")


if __name__ == "__main__":
    main()

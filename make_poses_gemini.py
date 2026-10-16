#!/usr/bin/env python3
"""記事動画の語り手（assets_video/presenter.png）のポーズ違いを Gemini の画像生成で作る。

    python3 make_poses_gemini.py <名前> "<ポーズの説明>" [-o assets_video/poses_anime] [--model gemini-3-pro-image]

元の絵と同じ人物・服・部屋・画角のまま、ポーズだけを変えるよう頼む。出来上がりは 1920×1080 にそろえる。
GEMINI_API_KEY が必要（有料の枠で1枚あたり数円〜十数円）。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

from PIL import Image

KEEP = ("Edit this image. Keep exactly the same anime-style woman (same face, same brown hair in an updo, "
        "same glasses, same navy suit and white shirt), the same art style and colors, the same blurred "
        "lecture-room background with the projector screen on the right, and the same camera framing, "
        "position and size of the woman. Do not add any text. Change only this: ")

# 全サイト紹介の長尺動画用（2026-10-13 オーナー依頼）: 画面の中央に全身で立つ語り手
KEEP_FULL = ("Using this image as the character reference, draw exactly the same anime-style woman (same face, "
             "same brown hair in an updo, same glasses, same navy suit, white shirt and skirt), in the same art "
             "style and colors. Show her FULL BODY from head to shoes, standing in the CENTER of a 16:9 frame, "
             "facing the viewer, with some empty space above her head and below her feet. Background: the same "
             "kind of softly blurred bright lecture room, without any screen behind her. Do not add any text. "
             "Pose and expression: ")


# 全サイト紹介の長尺動画用（2026-10-16 オーナー指示）: 記事動画と同じ大きさ（腰から上）で、背景と立ち位置を替える。
# 背景の説明は --bg で渡す
KEEP_RIN = ("Using this image as the character reference, draw exactly the same anime-style woman (same face, same brown "
            "hair in an updo, same glasses, same navy suit and white shirt) in the same art style, colors and the SAME "
            "SIZE in frame (from the waist up, as large as in this image). Place her on the RIGHT side of a 16:9 frame, "
            "body turned slightly to the left toward a large blank white presentation screen that fills the LEFT half "
            "of the frame. Do not add any text. Background: ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("pose")
    ap.add_argument("-o", "--outdir", default="assets_video/poses_anime")
    ap.add_argument("--src", default="assets_video/presenter.png")
    ap.add_argument("--model", default="gemini-3-pro-image")
    ap.add_argument("--full", action="store_true", help="全身・画面中央の語り手として描く（KEEP_FULL）")
    ap.add_argument("--rin-bg", default=None, help="全サイト紹介動画の構図（右に立ち、左にスクリーン）。背景の説明")
    a = ap.parse_args()
    key = os.environ.get("GEMINI_API_KEY") or sys.exit("GEMINI_API_KEY がありません")
    src = base64.b64encode(Path(a.src).read_bytes()).decode()
    body = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/png", "data": src}},
                                    {"text": (KEEP_RIN + a.rin_bg + ". Pose and expression: " if a.rin_bg
                                              else KEEP_FULL if a.full else KEEP) + a.pose}]}],
            "generationConfig": {"responseModalities": ["IMAGE"],
                                 "imageConfig": {"aspectRatio": "16:9"}}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{a.model}:generateContent",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        res = json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        sys.exit(f"生成に失敗しました: {e.code} {e.read()[:500]!r}")
    for part in res.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        data = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
        if data:
            im = Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
            print(f"生成: {im.size}")
            out = Path(a.outdir) / f"{a.name}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            im.resize((1920, 1080), Image.LANCZOS).save(out)
            print(f"保存: {out}")
            return
    sys.exit(f"画像が返りませんでした: {json.dumps(res, ensure_ascii=False)[:500]}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""語り手のポーズの絵を切り抜いて、動画づくりに使う素材にする（初回・ポーズを足したときだけ実行）。

    pip install rembg onnxruntime
    python3 make_pose_cutouts.py base=assets_video/presenter.png present=poses/present.png ... \\
        -o assets_video/poses_anime --room assets_video/room_blur.png

- 各ポーズを、アニメの絵向けの切り抜き（rembg の isnet-anime）で背景から外し、透明つきの PNG にする
- 人物のいない背景（room_clean.png）も作る: 元の絵（最初のポーズ）から、全ポーズの人物の形を
  少し広めに消し、無人の部屋の絵で埋める（ポーズを替えたり体を揺らしたりしても、すき間が自然に見える）
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("poses", nargs="+", help="名前=絵のファイル（最初が元の絵）")
    ap.add_argument("-o", "--outdir", default="assets_video/poses_anime")
    ap.add_argument("--room", default="assets_video/room_blur.png")
    a = ap.parse_args()
    from rembg import new_session, remove

    sess = new_session("isnet-anime")
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    union = None
    first = None
    for spec in a.poses:
        name, path = spec.split("=", 1)
        im = Image.open(path).convert("RGB").resize((1920, 1080), Image.LANCZOS)
        first = first or im
        m = np.asarray(remove(im, session=sess, only_mask=True))
        rgba = np.dstack([np.asarray(im), m])
        Image.fromarray(rgba, "RGBA").save(out / f"{name}.png")
        union = m if union is None else np.maximum(union, m)
        print(f"切り抜き: {name}")
    wide = cv2.dilate((union > 40).astype(np.uint8), np.ones((41, 41), np.uint8))
    k = cv2.GaussianBlur(wide.astype(np.float32), (0, 0), 8)[..., None]
    room = np.asarray(Image.open(a.room).convert("RGB").resize((1920, 1080), Image.LANCZOS)).astype(np.float32)
    clean = np.asarray(first).astype(np.float32) * (1 - k) + room * k
    Image.fromarray(clean.astype(np.uint8)).save(out / "room_clean.png")
    print(f"背景: {out / 'room_clean.png'}")


if __name__ == "__main__":
    main()

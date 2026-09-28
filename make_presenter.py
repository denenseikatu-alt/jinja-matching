#!/usr/bin/env python3
"""語り手の立ち絵（切り抜き）を作る。ポーズ集の画像を切り分け、背景を消し、顔を差し替える。

    python3 make_presenter.py --sheet poses.png --grid 3x2 \\
        --names present,point,surprised,think,hands,thumbsup \\
        --face face.webp --swap present,point,hands,thumbsup \\
        -o assets_video/poses

- ポーズ集は無地の背景で、人物が格子状に並んだ1枚絵を想定する
- 背景は四辺とつながった「背景色に近い領域」として消す（白いシャツは残る）
- --face の写真の顔を、目の位置で合わせて --swap のポーズに貼る。
  写真の顔は表情が1種類なので、驚き・考え中など表情の違うポーズには貼らない
- 写真が白黒に近くても、貼る先の肌の色に合わせて色をつけ、境目はポアソン合成でなじませる
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def detect_eyes(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """顔と両目を探す。見つかれば (左目, 右目) の中心座標を返す。"""
    g = cv2.equalizeHist(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    fc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    ec = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    faces = fc.detectMultiScale(g, 1.08, 5, minSize=(g.shape[1] // 10,) * 2)
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    eyes = ec.detectMultiScale(g[y:y + h * 6 // 10, x:x + w], 1.05, 4,
                               minSize=(w // 10,) * 2)
    pts = [np.array([x + a + c / 2, y + b + d / 2]) for a, b, c, d in eyes]
    best = None
    for i in range(len(pts)):
        for j in range(len(pts)):
            p, q = pts[i], pts[j]
            dx, dy = q[0] - p[0], abs(q[1] - p[1])
            # 左右に顔幅の25〜60%離れ、高さがほぼ揃っている組を両目とみなす
            if 0.25 * w < dx < 0.6 * w and dy < 0.12 * w:
                score = dy - 0.1 * dx
                if best is None or score < best[0]:
                    best = (score, p, q)
    return (best[1], best[2]) if best else None


def face_mask(shape: tuple[int, int], left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """眉の下からあごまでを覆う楕円（ぼかし付き、0〜1）。"""
    d = np.linalg.norm(right - left)
    mid = (left + right) / 2
    ang = np.degrees(np.arctan2(right[1] - left[1], right[0] - left[0]))
    center = mid + np.array([-np.sin(np.radians(ang)), np.cos(np.radians(ang))]) * 0.72 * d
    m = np.zeros(shape, np.float32)
    cv2.ellipse(m, (int(center[0]), int(center[1])), (int(0.98 * d), int(1.06 * d)),
                ang, 0, 360, 1.0, -1)
    k = int(d * 0.18) | 1
    return cv2.GaussianBlur(m, (k, k), 0)


def swap_face(target: np.ndarray, src: np.ndarray,
              src_eyes: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    tgt_eyes = detect_eyes(target)
    if tgt_eyes is None:
        print("    貼り先の顔が見つからないので、このポーズは生成した顔のままにします")
        return target
    (sl, sr), (tl, tr) = src_eyes, tgt_eyes
    # 両目を合わせる相似変換（拡大縮小・回転・平行移動）
    sv, tv = sr - sl, tr - tl
    scale = np.linalg.norm(tv) / np.linalg.norm(sv)
    rot = np.arctan2(tv[1], tv[0]) - np.arctan2(sv[1], sv[0])
    c, s = scale * np.cos(rot), scale * np.sin(rot)
    M = np.array([[c, -s, 0], [s, c, 0]], np.float64)
    M[:, 2] = tl - M[:, :2] @ sl
    h, w = target.shape[:2]
    warped = cv2.warpAffine(src, M, (w, h), flags=cv2.INTER_CUBIC,
                            borderMode=cv2.BORDER_REFLECT)
    mask = face_mask((h, w), tl, tr)
    inside = mask > 0.5
    # 明るさは写真の濃淡を、色味は貼り先の肌に合わせる（写真が白黒に近くても肌色になる）
    ws = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB).astype(np.float32)
    ts = cv2.cvtColor(target, cv2.COLOR_BGR2LAB).astype(np.float32)
    L_s, L_t = ws[..., 0][inside], ts[..., 0][inside]
    ws[..., 0] = (ws[..., 0] - L_s.mean()) / (L_s.std() + 1e-6) * L_t.std() + L_t.mean()
    for ch in (1, 2):
        mean_t = ts[..., ch][inside].mean()
        ws[..., ch] = 0.5 * ts[..., ch] + 0.5 * mean_t + (ws[..., ch] - ws[..., ch][inside].mean())
    colored = cv2.cvtColor(np.clip(ws, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
    # 境目はポアソン合成でなじませる
    m8 = (mask > 0.35).astype(np.uint8) * 255
    ys, xs = np.where(m8 > 0)
    center = (int((xs.min() + xs.max()) / 2), int((ys.min() + ys.max()) / 2))
    try:
        out = cv2.seamlessClone(colored, target, m8, center, cv2.NORMAL_CLONE)
    except cv2.error:
        a = mask[..., None]
        out = (colored * a + target * (1 - a)).astype(np.uint8)
    return out


def cut_out(bgr: np.ndarray) -> np.ndarray:
    """無地の背景を消して RGBA にする。背景は四辺とつながった背景色の領域。"""
    h, w = bgr.shape[:2]
    border = np.concatenate([bgr[0], bgr[-1], bgr[:, 0], bgr[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(bgr.astype(np.float32) - bg, axis=2)
    near = (dist < 28).astype(np.uint8)
    _, labels = cv2.connectedComponents(near)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    bgmask = np.isin(labels, edge[edge != 0])
    # 四辺とつながらない背景（腕と体のすき間など）は残す。白いシャツと背景の灰色が
    # 近く、消そうとするとシャツに穴が開くため（縮小版で確認）
    fg = (~bgmask).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # 人物（いちばん大きな塊）だけを残す。隣のコマの切れ端や点状のノイズを除く
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg)
    if n > 1:
        keep = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        fg = (lab == keep).astype(np.uint8)
    alpha = fg * 255
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    rgba[..., 3] = alpha
    ys, xs = np.where(alpha > 20)
    return rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--grid", default="3x2", help="列x行")
    ap.add_argument("--names", required=True, help="ポーズ名をカンマ区切りで（左上から右へ）")
    ap.add_argument("--face", help="差し替える顔の写真")
    ap.add_argument("--swap", default="", help="顔を差し替えるポーズ名（カンマ区切り）")
    ap.add_argument("-o", "--outdir", default="assets_video/poses")
    args = ap.parse_args()

    sheet = cv2.imread(args.sheet)
    cols, rows = map(int, args.grid.lower().split("x"))
    names = args.names.split(",")
    swap = set(filter(None, args.swap.split(",")))
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    src = src_eyes = None
    if args.face:
        src = cv2.imread(args.face)
        src_eyes = detect_eyes(src)
        if src_eyes is None:
            raise SystemExit("顔写真の目が見つかりませんでした")

    H, W = sheet.shape[:2]
    for k, name in enumerate(names):
        r, c = divmod(k, cols)
        cell = sheet[r * H // rows:(r + 1) * H // rows, c * W // cols:(c + 1) * W // cols].copy()
        if src is not None and name in swap:
            cell = swap_face(cell, src, src_eyes)
        rgba = cut_out(cell)
        cv2.imwrite(str(out / f"{name}.png"), rgba)
        print(f"  {name}: {rgba.shape[1]}x{rgba.shape[0]}" + ("（顔を差し替え）" if name in swap else ""))


if __name__ == "__main__":
    main()

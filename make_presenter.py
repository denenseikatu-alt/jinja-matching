#!/usr/bin/env python3
"""語り手の立ち絵（切り抜き）を作る。ポーズ集の画像を切り分け、背景を消し、顔を差し替える。

    python3 make_presenter.py --sheet poses.png --grid 3x2 \\
        --names present,point,surprised,think,hands,thumbsup \\
        --face face.webp --swap present,point,hands,thumbsup \\
        -o assets_video/poses

- ポーズ集は無地の背景で、人物が格子状に並んだ1枚絵を想定する
- 背景は四辺とつながった「背景色に近い領域」として消す（白いシャツは残る）
- --face の写真の顔を --swap のポーズに貼る。MediaPipe の顔の特徴点（478点）で顔を三角形に
  分け、貼り先の向きに合わせて1枚ずつ変形する（~/models/face_landmarker.task が必要。
  無ければ両目の位置だけで合わせるが、顔の向きが違うと不自然になる）
  写真の顔は表情が1種類なので、驚き・考え中など表情の違うポーズには貼らない
- 明るさは写真の濃淡を、色は貼り先の肌・唇の色を使う（写真が白黒に近くても自然な色になる）。
  境目はポアソン合成でなじませる

準備（初回のみ）:
    pip install opencv-python-headless mediapipe
    apt-get install -y libegl1 libgles2
    curl -o ~/models/face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def detect_eyes(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """顔と両目を探す。見つかれば (左目, 右目) の中心座標を返す。

    小さな顔は検出されにくいので、画像を拡大してから探す。胸元などを顔と誤検出する
    ことがあるため、候補が複数あればいちばん上のものを顔とみなす。
    """
    zoom = max(1.0, 1024 / max(bgr.shape[:2]))
    big = cv2.resize(bgr, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
    g = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    faces = []
    for name in ("haarcascade_frontalface_alt2.xml", "haarcascade_frontalface_default.xml"):
        cc = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        faces = [f for f in cc.detectMultiScale(g, 1.05, 3, minSize=(g.shape[1] // 8,) * 2)]
        if faces:
            break
    if not faces:
        return None
    x, y, w, h = min(faces, key=lambda f: f[1])
    ec = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    eyes = ec.detectMultiScale(g[y:y + h * 6 // 10, x:x + w], 1.05, 3, minSize=(w // 12,) * 2)
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
    if not best:
        return None
    return best[1] / zoom, best[2] / zoom


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
              src_eyes: tuple[np.ndarray, np.ndarray], tgt_eyes=None) -> np.ndarray:
    tgt_eyes = tgt_eyes or detect_eyes(target)
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


# 顔の外周（あご側）と眉の上端で囲む。額は前髪がかかるので含めない
_REGION = [234, 93, 132, 58, 172, 136, 150, 149, 176, 148, 152, 377, 400, 378, 379, 365, 397,
           288, 361, 323, 454, 300, 293, 334, 296, 336, 107, 66, 105, 63, 70]
_landmarker = None


def landmarks(bgr: np.ndarray) -> np.ndarray | None:
    """MediaPipe の顔の特徴点（478点）。使えない環境なら None。"""
    global _landmarker
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
    except ImportError:
        return None
    if _landmarker is None:
        model = Path.home() / "models" / "face_landmarker.task"
        if not model.exists():
            return None
        _landmarker = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=mpt.BaseOptions(model_asset_path=str(model)), num_faces=1))
    rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    res = _landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not res.face_landmarks:
        return None
    h, w = bgr.shape[:2]
    return np.array([[p.x * w, p.y * h] for p in res.face_landmarks[0]], np.float32)


def swap_face_mesh(target: np.ndarray, src: np.ndarray, sp: np.ndarray,
                   tp: np.ndarray) -> np.ndarray:
    """特徴点で三角形に分け、1枚ずつ貼り先の形に変形して貼る（顔の向きの違いも吸収する）。"""
    h, w = target.shape[:2]
    warped = np.zeros_like(target)
    rect = (0, 0, w, h)
    sub = cv2.Subdiv2D(rect)
    inside = [i for i, (x, y) in enumerate(tp) if 0 <= x < w and 0 <= y < h]
    for i in inside:
        sub.insert((float(tp[i][0]), float(tp[i][1])))
    tin = tp[inside]
    for t in sub.getTriangleList():
        idx = []
        for k in range(3):
            dist = np.linalg.norm(tin - t[2 * k:2 * k + 2], axis=1)
            j = int(np.argmin(dist))
            idx.append(inside[j] if dist[j] < 1.0 else None)
        if None in idx:
            continue
        s_tri, t_tri = sp[idx].astype(np.float32), tp[idx].astype(np.float32)
        x, y, bw, bh = cv2.boundingRect(t_tri)
        if bw == 0 or bh == 0:
            continue
        M = cv2.getAffineTransform(s_tri, (t_tri - [x, y]).astype(np.float32))
        patch = cv2.warpAffine(src, M, (bw, bh), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REFLECT)
        m = np.zeros((bh, bw), np.uint8)
        cv2.fillConvexPoly(m, np.int32(t_tri - [x, y]), 255)
        x1, y1 = min(x + bw, w), min(y + bh, h)
        roi = warped[y:y1, x:x1]
        mm = m[:y1 - y, :x1 - x] > 0
        roi[mm] = patch[:y1 - y, :x1 - x][mm]
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [np.int32(tp[_REGION])], 255)
    d = np.linalg.norm(tp[33] - tp[263])            # 両目の外側の距離
    mask = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=max(1, int(d * 0.03)))
    # 明るさは写真の濃淡、色味は貼り先の肌・唇の色をそのまま使う（写真が白黒でも自然な色になる）
    ws = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB).astype(np.float32)
    ts = cv2.cvtColor(target, cv2.COLOR_BGR2LAB).astype(np.float32)
    inm = mask > 0
    L_s, L_t = ws[..., 0][inm], ts[..., 0][inm]
    ws[..., 0] = (ws[..., 0] - L_s.mean()) / (L_s.std() + 1e-6) * L_t.std() + L_t.mean()
    ws[..., 1:] = ts[..., 1:]
    colored = cv2.cvtColor(np.clip(ws, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
    ys, xs = np.where(inm)
    center = (int((xs.min() + xs.max()) / 2), int((ys.min() + ys.max()) / 2))
    try:
        return cv2.seamlessClone(colored, target, mask, center, cv2.NORMAL_CLONE)
    except cv2.error:
        soft = cv2.GaussianBlur(mask, (0, 0), d * 0.04)[..., None] / 255.0
        return (colored * soft + target * (1 - soft)).astype(np.uint8)


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
    ap.add_argument("--eyes", help="貼り先の両目の位置を指定する JSON "
                    "（{ポーズ名: [[左x, 左y], [右x, 右y]]}、コマ内の座標）。自動検出が外れるとき用")
    ap.add_argument("-o", "--outdir", default="assets_video/poses")
    args = ap.parse_args()

    sheet = cv2.imread(args.sheet)
    cols, rows = map(int, args.grid.lower().split("x"))
    names = args.names.split(",")
    swap = set(filter(None, args.swap.split(",")))
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    src = src_eyes = src_lm = None
    if args.face:
        src = cv2.imread(args.face)
        src_eyes = detect_eyes(src)
        src_lm = landmarks(src)
        if src_eyes is None and src_lm is None:
            raise SystemExit("顔写真の目が見つかりませんでした")

    manual = {}
    if args.eyes:
        import json
        manual = {k: (np.array(v[0], float), np.array(v[1], float))
                  for k, v in json.loads(Path(args.eyes).read_text(encoding="utf-8")).items()}
    H, W = sheet.shape[:2]
    for k, name in enumerate(names):
        r, c = divmod(k, cols)
        cell = sheet[r * H // rows:(r + 1) * H // rows, c * W // cols:(c + 1) * W // cols].copy()
        swapped = False
        if src is not None and name in swap:
            tp = landmarks(cell)
            if src_lm is not None and tp is not None:
                cell = swap_face_mesh(cell, src, src_lm, tp)
                swapped = True
            else:
                new = swap_face(cell, src, src_eyes, manual.get(name))
                swapped = new is not cell
                cell = new
        rgba = cut_out(cell)
        cv2.imwrite(str(out / f"{name}.png"), rgba)
        print(f"  {name}: {rgba.shape[1]}x{rgba.shape[0]}" + ("（顔を差し替え）" if swapped else ""))


if __name__ == "__main__":
    main()

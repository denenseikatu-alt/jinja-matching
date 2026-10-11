"""語り手の1枚絵に、体の揺れ・呼吸・首の動き（かしげ・うなずき）を付ける。

build_talking.py から使う。AI の動画生成ではなく、絵を切り抜いて少しずつ変形するだけ。

- 切り抜き: 語り手のいる絵（presenter.png）と、同じ部屋の無人の絵（room_blur.png）の差から人物の形を取る
- 体: 腰のあたりを軸に、ゆっくり左右に揺れ、呼吸で少し上下する。場面が変わると、スクリーンの方へ少し身を乗り出す
- 首: 首の付け根を軸に、顔だけがゆっくりかしげる。話し始めにうなずき、声の大きさに合わせて小さく上下する
- 動かして空いたすき間には、無人の部屋の絵が見える
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image


def _smooth(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


class Motion:
    def __init__(self, base: Image.Image, room: Image.Image, cfg: dict, fps: int):
        self.fps = fps
        self.cfg = cfg
        b = np.asarray(base).astype(np.float32)
        r = np.asarray(room.resize(base.size, Image.LANCZOS)).astype(np.float32)
        h, w = b.shape[:2]
        # 1. 人物の形: ぼかした2枚の差が大きい所のうち、いちばん大きなかたまり
        d = np.abs(cv2.GaussianBlur(b, (0, 0), 10) - cv2.GaussianBlur(r, (0, 0), 10)).sum(2)
        m = (d > cfg.get("threshold", 40)).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
        m = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
        # 服の白い所などが部屋と似ていて欠けるので、行ごとに左端から右端までを埋める
        for y in np.nonzero(m.any(1))[0]:
            xs = np.nonzero(m[y])[0]
            m[y, xs[0]:xs[-1] + 1] = 1
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        self.mask = cv2.GaussianBlur(m.astype(np.float32), (0, 0), 2.0)
        ys, xs = np.nonzero(m)
        pad = 40
        self.box = (max(0, xs.min() - pad), max(0, ys.min() - pad), min(w, xs.max() + pad), h)
        # 2. 人物を消した背景（人物の所は無人の部屋で埋める）。輪郭の残りが出ないよう、少し広めに消す
        wide = cv2.dilate(m, np.ones((31, 31), np.uint8))
        a = cv2.GaussianBlur(wide.astype(np.float32), (0, 0), 6)[..., None]
        self.clean = Image.fromarray((b * (1 - a) + r * a).astype(np.uint8))
        x0, y0, x1, y1 = self.box
        gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        self.gx, self.gy = gx, gy
        nx, ny = cfg["neck"]
        # 首から上だけが首の動きに従う重み（あごの下から肩までで 1 → 0）
        self.head_w = 1.0 - _smooth((gy - (ny - 50)) / 110.0)
        self.neck = (nx, ny)
        self.pivot = cfg.get("pivot", [nx, h + 150])

    def frame(self, char: Image.Image, bg: Image.Image, t: float, level: float,
              nod: float, lean: float) -> Image.Image:
        """char: 口とまぶたを描いた元の絵。bg: 人物を消した背景（スクリーン入り）。
        level: 声の大きさ（0〜1）。nod: うなずきの強さ（0〜1）。lean: 身を乗り出す強さ（0〜1）。"""
        c = self.cfg
        # 体: 左右の揺れ（度）と呼吸
        body = (c.get("sway_deg", 0.6) * math.sin(2 * math.pi * t / 8.3)
                - c.get("lean_deg", 1.2) * lean)
        breath = 1.0 + c.get("breath", 0.005) * math.sin(2 * math.pi * t / 3.9)
        # 首: かしげ（度）・うなずき（下へ）・話すときの小さな上下
        tilt = (c.get("tilt_deg", 1.6) * math.sin(2 * math.pi * t / 6.7 + 0.8)
                + 0.6 * math.sin(2 * math.pi * t / 2.9))
        dy_head = c.get("nod_px", 9) * nod + c.get("bob_px", 2.5) * level
        tilt += c.get("nod_tilt_deg", 1.0) * nod

        gx, gy = self.gx, self.gy
        # 逆向きの写像: 出力の点 → 元の絵の点
        # 体の回転と呼吸（腰の下を軸に）を戻す
        px, py = self.pivot
        th = math.radians(-body)
        ux, uy = gx - px, gy - py
        sx = px + (ux * math.cos(th) - uy * math.sin(th))
        sy = py + (ux * math.sin(th) + uy * math.cos(th)) / breath
        # 首の回転とうなずきを、首から上の重みつきで戻す
        nx, ny = self.neck
        th2 = math.radians(-tilt)
        vx, vy = sx - nx, sy - (ny + dy_head)
        hx = nx + vx * math.cos(th2) - vy * math.sin(th2)
        hy = ny + vx * math.sin(th2) + vy * math.cos(th2)
        wgt = self.head_w
        mapx = (sx * (1 - wgt) + hx * wgt).astype(np.float32)
        mapy = (sy * (1 - wgt) + hy * wgt).astype(np.float32)

        x0, y0, x1, y1 = self.box
        src = np.asarray(char)
        warped = cv2.remap(src, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        alpha = cv2.remap(self.mask, mapx, mapy, cv2.INTER_LINEAR, borderValue=0)[..., None]
        out = np.asarray(bg).copy()
        region = out[y0:y1, x0:x1].astype(np.float32)
        out[y0:y1, x0:x1] = (region * (1 - alpha) + warped.astype(np.float32) * alpha).astype(np.uint8)
        return Image.fromarray(out)


def nod_curve(onsets: list[float], n_frames: int, fps: int) -> np.ndarray:
    """話し始めの時刻ごとに、0.6秒ほどの「うなずき」（下がって戻る）を入れる。"""
    out = np.zeros(n_frames, dtype=np.float32)
    span = int(0.6 * fps)
    shape = np.sin(np.linspace(0, math.pi, span)) ** 2
    for t in onsets:
        i = int(t * fps)
        j = min(n_frames, i + span)
        if i < n_frames:
            out[i:j] = np.maximum(out[i:j], shape[:j - i])
    return out


def lean_curve(scene_starts: list[float], n_frames: int, fps: int) -> np.ndarray:
    """場面が変わるたびに、スクリーンの方へ少し身を乗り出して戻る（約2.5秒）。"""
    out = np.zeros(n_frames, dtype=np.float32)
    span = int(2.5 * fps)
    x = np.linspace(0, 1, span)
    shape = np.where(x < 0.3, _smooth(x / 0.3), 1 - _smooth((x - 0.3) / 0.7))
    for t in scene_starts[1:]:
        i = int(t * fps)
        j = min(n_frames, i + span)
        if i < n_frames:
            out[i:j] = np.maximum(out[i:j], shape[:j - i])
    return out

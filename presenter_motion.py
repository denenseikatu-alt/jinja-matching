"""語り手の1枚絵に、体の揺れ・呼吸・首の動き（かしげ・うなずき）を付ける。

build_talking.py から使う。AI の動画生成ではなく、絵を切り抜いて少しずつ変形するだけ。

- 切り抜き: make_pose_cutouts.py で作った透明つきのポーズの絵（なければ、無人の部屋の絵との差から取る）
- ポーズ: 場面に合わせて、スライドを手で示す・指さす・スクリーンを見る・両手で説明する・手を振る、に切り替える
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
    """1つのポーズの切り抜き（alpha: 0〜1）を、体と首の動きに合わせて変形して背景に重ねる。"""

    def __init__(self, alpha: np.ndarray, cfg: dict, fps: int):
        self.fps = fps
        self.cfg = cfg
        h, w = alpha.shape
        self.mask = alpha.astype(np.float32)
        ys, xs = np.nonzero(self.mask > 0.05)
        pad = 40
        self.box = (max(0, xs.min() - pad), max(0, ys.min() - pad), min(w, xs.max() + pad), h)
        x0, y0, x1, y1 = self.box
        # 写像はなめらかなので、4画素おきに計算してから拡大する（書き出しを速くするため）
        self.size = (x1 - x0, y1 - y0)
        gy, gx = np.mgrid[y0:y1 + 4:4, x0:x1 + 4:4].astype(np.float32)
        self.gx, self.gy = gx, gy
        nx, ny = cfg["neck"]
        # 首から上だけが首の動きに従う重み（あごの下から肩までで 1 → 0）
        self.head_w = 1.0 - _smooth((gy - (ny - 50)) / 110.0)
        self.mask_box = np.ascontiguousarray(self.mask)
        self.neck = (nx, ny)
        self.pivot = cfg.get("pivot", [nx, h + 150])

    @staticmethod
    def from_room(base: Image.Image, room: Image.Image, cfg: dict, fps: int) -> "Motion":
        """切り抜きがないとき: 語り手のいる絵と無人の部屋の絵の差から人物の形を取る。self.clean に人物を消した背景。"""
        b = np.asarray(base).astype(np.float32)
        r = np.asarray(room.resize(base.size, Image.LANCZOS)).astype(np.float32)
        h, w = b.shape[:2]
        d = np.abs(cv2.GaussianBlur(b, (0, 0), 10) - cv2.GaussianBlur(r, (0, 0), 10)).sum(2)
        m = (d > cfg.get("threshold", 40)).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
        m = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
        # 服の白い所などが部屋と似ていて欠けるので、穴を埋める
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        xs = np.nonzero(m[-1])[0]
        if xs.size:
            m[-1, xs[0]:xs[-1] + 1] = 1
        outside = m.copy() * 255
        cv2.floodFill(outside, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 128)
        m = (outside != 128).astype(np.uint8)
        mo = Motion(cv2.GaussianBlur(m.astype(np.float32), (0, 0), 2.0), cfg, fps)
        wide = cv2.dilate(m, np.ones((31, 31), np.uint8))
        a = cv2.GaussianBlur(wide.astype(np.float32), (0, 0), 6)[..., None]
        mo.clean = Image.fromarray((b * (1 - a) + r * a).astype(np.uint8))
        return mo

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
        bw, bh = self.size
        ch, cw = self.gx.shape
        # 粗い格子の端が箱の端にくるように拡大する
        mapx = cv2.resize((sx * (1 - wgt) + hx * wgt).astype(np.float32), (cw * 4, ch * 4),
                          interpolation=cv2.INTER_LINEAR)[:bh, :bw]
        mapy = cv2.resize((sy * (1 - wgt) + hy * wgt).astype(np.float32), (cw * 4, ch * 4),
                          interpolation=cv2.INTER_LINEAR)[:bh, :bw]

        x0, y0, x1, y1 = self.box
        src = np.asarray(char)
        warped = cv2.remap(src, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        alpha = cv2.remap(self.mask_box, mapx, mapy, cv2.INTER_LINEAR, borderValue=0)
        out = np.array(bg)
        region = np.ascontiguousarray(out[y0:y1, x0:x1])
        out[y0:y1, x0:x1] = cv2.blendLinear(warped, region, alpha, 1.0 - alpha)
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


FADE = 0.25   # ポーズを切り替えるときに重ねる秒数


def pose_timeline(scenes: list[dict], scene_spans: list[tuple[float, float]],
                  line_starts: list[float], n_frames: int, fps: int, have: set[str]) -> list[str]:
    """フレームごとのポーズ名。基本は "base"。場面の頭でスクリーンを見てから手で示し、
    ときどき両手で説明する。最初のあいさつと最後のお礼では手を振る。"""
    poses = ["base"] * n_frames

    def put(a: float, b: float, name: str) -> None:
        if name in have:
            for i in range(max(0, int(a * fps)), min(n_frames, int(b * fps))):
                poses[i] = name

    last = len(scenes) - 1
    for k, (scene, (a, b)) in enumerate(zip(scenes, scene_spans)):
        starts = [t for t in line_starts if a <= t < b]
        if k == 0:
            put(starts[0] if starts else a, (starts[0] if starts else a) + 2.4, "lean")
        elif k == last:
            put(a + 0.3, min(b, a + 3.5), "present")
            if starts:
                put(starts[-1], b + 5.0, "lean")
        else:
            if scene.get("bullets"):
                put(a, a + 1.0, "look")
                put(a + 1.0, min(b, a + 4.2), "present" if k % 2 else "point")
            if len(starts) > 2 and k % 2 == 0:
                put(starts[2], min(b, starts[2] + 2.6), "explain")
            elif len(starts) > 3:
                put(starts[3], min(b, starts[3] + 1.4), "look")
    return poses


def fade_at(poses: list[str], i: int, fps: int) -> tuple[str, str, float]:
    """(今のポーズ, 直前のポーズ, 今のポーズの重み 0〜1)。切り替わってから FADE 秒かけて重ねる。"""
    cur = poses[i]
    r = i
    span = int(FADE * fps)
    while r > 0 and poses[r - 1] == cur and i - r < span:
        r -= 1
    if r == 0 or poses[r - 1] == cur:
        return cur, cur, 1.0
    return cur, poses[r - 1], min(1.0, (i - r + 1) / span)

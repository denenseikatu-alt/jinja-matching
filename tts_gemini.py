"""Gemini の音声生成（TTS）で1文を WAV にする。

    GEMINI_API_KEY を環境変数に置いておく。
    声（prebuilt voice）と読み方の指示は台本の "voice" ブロックで変えられる:
        "voice": {"engine": "gemini", "name": "Leda",
                  "style": "Say in a bright, friendly young woman's voice"}

style は英語で書く。「指示: 本文」の形で送ると本文だけが読まれる
（日本語で指示を書くと、指示文まで読み上げてしまうことを文字起こしで確認した）。

モデル名は GEMINI_TTS_MODEL で指定できる。指定がなく既定のモデルが無い場合は、
使えるモデルの一覧から名前に "tts" を含むものを選ぶ。
"""

from __future__ import annotations

import base64
import json

import numpy as np
import os
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

API = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
RATE = 24000
_model_cache: str | None = None


def _key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY がありません（Gemini の音声生成に必要です）。")
    return key


def _request(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "x-goog-api-key": _key(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def pick_model() -> str:
    global _model_cache
    if _model_cache:
        return _model_cache
    wanted = os.environ.get("GEMINI_TTS_MODEL")
    if wanted:
        _model_cache = wanted
        return wanted
    names = []
    token = ""
    while True:
        page = _request(f"{API}/models?pageSize=200" + (f"&pageToken={token}" if token else ""))
        names += [m["name"].split("/", 1)[1] for m in page.get("models", [])]
        token = page.get("nextPageToken", "")
        if not token:
            break
    tts = [n for n in names if "tts" in n]
    if not tts:
        sys.exit("このキーで使える Gemini の音声生成モデルが見つかりません。")
    _model_cache = DEFAULT_MODEL if DEFAULT_MODEL in tts else sorted(tts)[-1]
    return _model_cache


def _generate(prompt: str, voice: str) -> bytes:
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    for attempt in range(8):
        try:
            res = _request(f"{API}/models/{pick_model()}:generateContent", body)
            part = res["candidates"][0]["content"]["parts"][0]["inlineData"]
            return base64.b64decode(part["data"])
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 503) and attempt < 7:
                wait = 10 * (attempt + 1)
                try:
                    for d in json.loads(detail)["error"].get("details", []):
                        if "retryDelay" in d:
                            wait = max(wait, float(d["retryDelay"].rstrip("s")) + 1)
                except Exception:
                    pass
                print(f"    Gemini {e.code}、{wait:.0f}秒待って再試行します", flush=True)
                time.sleep(wait)
                continue
            sys.exit(f"Gemini の音声生成に失敗しました（{e.code}）: {detail[:300]}")
        except (KeyError, IndexError):
            if attempt < 7:
                time.sleep(5)
                continue
            sys.exit(f"Gemini から音声が返りませんでした: {str(res)[:300]}")
    sys.exit("Gemini の音声生成に失敗しました")


def _write(pcm: bytes, out_path: Path) -> None:
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def synth(text: str, out_path: Path, voice: str = "Leda", style: str = "") -> None:
    """1文を1回の生成で作る。"""
    pcm = _generate(f"{style}: {text}" if style else text, voice)
    _write(_trim(pcm), out_path)


def synth_lines(lines: list[str], out_paths: list[Path], voice: str = "Leda",
                style: str = "") -> None:
    """複数の文を1回の生成でまとめて読ませ、息継ぎの無音で文ごとに切り分ける。

    無料枠は1日あたりの回数制限が厳しいため（モデルごとに10回など）、
    1文ずつではなく数場面分をまとめて頼む。
    """
    directive = (style + ", pausing briefly between lines") if style else "Read aloud"
    # 空行で区切ると、文と文の間の間（ま）がはっきりして切り分けやすい
    pcm = _generate(directive + ":\n\n" + "\n\n".join(lines), voice)
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    cuts = _find_cuts(a, [len(x) for x in lines])
    bounds = [0] + cuts + [len(a)]
    for k, path in enumerate(out_paths):
        seg = (a[bounds[k]:bounds[k + 1]] * 32767).astype(np.int16).tobytes()
        _write(_trim(seg), path)


def _find_cuts(a: np.ndarray, lengths: list[int]) -> list[int]:
    """文字数の比から各文の境目のおよその時刻を出し、そこに近い無音で切る。"""
    win = int(RATE * 0.02)
    n = len(a) // win
    rms = np.sqrt((a[: n * win].reshape(n, win) ** 2).mean(axis=1))
    silent = rms < max(0.008, rms.max() * 0.03)
    # 0.14秒以上続く無音を切れ目の候補にする（中央で切る）
    gaps, run = [], 0
    for i, sv in enumerate(list(silent) + [False]):
        if sv:
            run += 1
        elif run:
            if run * win >= RATE * 0.14:
                gaps.append(((i - run / 2) * win, run * win / RATE))
            run = 0
    loud = np.where(~silent)[0]
    t0, t1 = loud[0] * win, (loud[-1] + 1) * win
    K = len(lengths) - 1
    if K <= 0:
        return []
    rate = (t1 - t0) / max(sum(lengths), 1)            # 1文字あたりのサンプル数
    scale = rate * 6                                    # 約6文字ぶんのずれを1とする
    C = len(gaps)
    if C < K:
        acc, cuts = 0, []
        for L in lengths[:-1]:
            acc += L
            cuts.append(int(t0 + rate * acc))
        return cuts
    pos = [g[0] for g in gaps]
    bonus = [1.5 * min(g[1], 1.0) for g in gaps]

    def seg(k: int, a: float, b: float) -> float:
        """k 番目の文の長さが、文字数から見込む長さにどれだけ近いか。"""
        return abs((b - a) - lengths[k] * rate) / scale

    # 動的計画法: 各文の長さが文字数に見合い、切れ目の無音は長いほど好ましい
    INF = float("inf")
    cost = [[INF] * C for _ in range(K)]
    back = [[-1] * C for _ in range(K)]
    for j in range(C):
        cost[0][j] = seg(0, t0, pos[j]) - bonus[j]
    for k in range(1, K):
        for j in range(k, C):
            best, arg = INF, -1
            for i in range(k - 1, j):
                v = cost[k - 1][i] + seg(k, pos[i], pos[j])
                if v < best:
                    best, arg = v, i
            cost[k][j] = best - bonus[j]
            back[k][j] = arg
    j = min(range(K - 1, C), key=lambda x: cost[K - 1][x] + seg(K, pos[x], t1))
    picks = []
    for k in range(K - 1, -1, -1):
        picks.append(int(pos[j]))
        j = back[k][j]
    return picks[::-1]


def _trim(pcm: bytes, margin: float = 0.08) -> bytes:
    """前後の無音を詰める。文と文の間は台本側の間（0.35秒など）で揃えるため。"""
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    win = int(RATE * 0.02)
    n = len(a) // win
    if n == 0:
        return pcm
    rms = np.sqrt((a[: n * win].reshape(n, win) ** 2).mean(axis=1))
    loud = np.where(rms > max(0.01, rms.max() * 0.03))[0]
    if loud.size == 0:
        return pcm
    start = max(0, loud[0] * win - int(RATE * margin))
    end = min(len(a), (loud[-1] + 1) * win + int(RATE * margin))
    return pcm[start * 2:end * 2]


CREDIT = "音声: Google Gemini（AI 音声合成）"

"""Gemini の音声生成（TTS）で1文を WAV にする。

    GEMINI_API_KEY を環境変数に置いておく。
    声（prebuilt voice）と読み方の指示は台本の "voice" ブロックで変えられる:
        "voice": {"engine": "gemini", "name": "Leda",
                  "style": "明るく親しみやすく、落ち着いて分かりやすく読み上げて"}

モデル名は GEMINI_TTS_MODEL で指定できる。指定がなく既定のモデルが無い場合は、
使えるモデルの一覧から名前に "tts" を含むものを選ぶ。
"""

from __future__ import annotations

import base64
import json
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


def synth(text: str, out_path: Path, voice: str = "Leda", style: str = "") -> None:
    prompt = f"{style}: {text}" if style else text
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
            pcm = base64.b64decode(part["data"])
            break
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
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


CREDIT = "音声: Google Gemini（AI 音声合成）"

"""Gemini の音声のうち、照合で合わなかった文だけを1文ずつ作り直す。

使い方: python3 tts_regen_lines.py <台本.json> <書き出し先> <文の番号> [<文の番号> ...]
（番号は audio/0001.wav から数えた通し番号。作り直しても合わない文は最後に LEFT として出す）
"""
import json
import sys
import wave
from pathlib import Path

import tts_gemini as t


def read(p: Path) -> bytes:
    with wave.open(str(p), "rb") as w:
        return w.readframes(w.getnframes())


def main() -> None:
    script, outdir, nums = sys.argv[1], Path(sys.argv[2]), [int(x) for x in sys.argv[3:]]
    d = json.loads(Path(script).read_text(encoding="utf-8"))
    t._CAPTION_REPLACE.update(d.get("caption_replace", {}))
    v = d["voice"]
    lines = [l for s in d["scenes"] for l in s["lines"]]
    left = []
    for n in nums:
        p = outdir / "audio" / f"{n:04d}.wav"
        for attempt in range(5):
            t.synth(lines[n - 1], p, voice=v.get("name", "Leda"), style=v.get("style", ""))
            r = t.verify([lines[n - 1]], [read(p)])
            print(f"  {n}文目 {attempt + 1}回目: {'一致' if r == '' else r}", flush=True)
            if r == "":
                break
        else:
            left.append(n)
    print("LEFT", left)


if __name__ == "__main__":
    main()

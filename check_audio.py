#!/usr/bin/env python3
"""完成した動画の音声に、雑音（無音から急な大音量・音割れ）がないか調べる。

    python3 check_audio.py out/video.mp4

問題があれば、その時刻を出して終了コード 1 で終わる。cloud/daily.sh がアップの直前に使う。

- 急な大音量: 0.1秒以上ほぼ無音（-45dB 未満）だったところから、10ms 以内に -6dB を超える。
  話し始めでもここまで急には大きくならない。Gemini の音声の末尾についた雑音がこれに当たった
- 音割れ: 最大値に張りついたサンプルが 20 個以上続く
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np

from build_video import ffmpeg_bin

RATE = 24000


def load(path: str) -> np.ndarray:
    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", path, "-f", "s16le", "-ac", "1",
                          "-ar", str(RATE), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def find_problems(x: np.ndarray) -> list[str]:
    problems = []
    win = int(RATE * 0.01)
    n = len(x) // win
    db = 20 * np.log10(np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1)) + 1e-9)
    for i in range(10, n):
        if db[i] > -6 and np.all(db[i - 10:i] < -45):
            problems.append(f"{i * 0.01:7.2f}秒: 無音から急に大音量（{db[i]:.0f}dB）")
    clip = np.abs(x) > 0.99
    run = 0
    for i, c in enumerate(clip):
        run = run + 1 if c else 0
        if run == 20:
            problems.append(f"{i / RATE:7.2f}秒: 音割れ")
    return problems


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    problems = find_problems(load(sys.argv[1]))
    if problems:
        print("音声に雑音があります:")
        for p in problems[:20]:
            print("  " + p)
        sys.exit(1)
    print("音声の検査 OK（急な大音量・音割れなし）")


if __name__ == "__main__":
    main()

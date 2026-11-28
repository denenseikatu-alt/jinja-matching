"""~/.video_env（cloud/unlock.sh が作る認証情報）を、まだ環境変数にないときだけ読みこむ。

コマンドの頭に `. ~/.video_env &&` を付けなくても動くようにするため。値は表示しない。
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path

PATH = Path.home() / ".video_env"


def load() -> None:
    if not PATH.exists():
        return
    for line in PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("export ") or "=" not in line:
            continue
        key, _, val = line[len("export "):].partition("=")
        key = key.strip()
        if key and key not in os.environ:
            parts = shlex.split(val) if val else [""]
            os.environ[key] = parts[0] if parts else ""

#!/usr/bin/env bash
# クラウド実行環境（Linux）で動画パイプラインを動かす準備。
# Python の依存を入れ、VOICEVOX ENGINE を取得して起動する。何度実行してもよい。
#
#   bash cloud/setup.sh
#
# ENGINE の配布物は約1.7GB。展開後を含めて4GB程度の空きが要る。

set -eu

V="${VOICEVOX_VERSION:-0.25.2}"
ENGINE_HOME="${VOICEVOX_HOME:-$HOME/voicevox}"
HOST="${VOICEVOX_HOST:-http://127.0.0.1:50021}"

echo "== Python の依存 =="
pip install -q pillow imageio-ffmpeg py7zr google-auth google-auth-oauthlib google-api-python-client

if curl -sS -m 5 "$HOST/version" >/dev/null 2>&1; then
  echo "== VOICEVOX ENGINE は起動済み: $(curl -sS -m 5 "$HOST/version") =="
  exit 0
fi

RUN="$ENGINE_HOME/linux-cpu-x64/run"
if [ ! -x "$RUN" ]; then
  echo "== VOICEVOX ENGINE $V を取得 =="
  mkdir -p "$ENGINE_HOME"
  ARCHIVE="$ENGINE_HOME/engine.7z"
  curl -sSL --retry 3 -o "$ARCHIVE" \
    "https://github.com/VOICEVOX/voicevox_engine/releases/download/$V/voicevox_engine-linux-cpu-x64-$V.7z.001"
  python3 -c "import py7zr, sys; py7zr.SevenZipFile(sys.argv[1]).extractall(sys.argv[2])" \
    "$ARCHIVE" "$ENGINE_HOME"
  rm -f "$ARCHIVE"
  chmod +x "$RUN"
fi

echo "== VOICEVOX ENGINE を起動 =="
(cd "$(dirname "$RUN")" && nohup ./run --host 127.0.0.1 --port 50021 >"$ENGINE_HOME/engine.log" 2>&1 &)
for _ in $(seq 1 60); do
  sleep 2
  if curl -sS -m 5 "$HOST/version" >/dev/null 2>&1; then
    echo "起動完了: $(curl -sS -m 5 "$HOST/version")"
    exit 0
  fi
done
echo "VOICEVOX が起動しませんでした。$ENGINE_HOME/engine.log:"
tail -20 "$ENGINE_HOME/engine.log"
exit 1

#!/usr/bin/env bash
# 毎日1本を無人で作ってアップロードする。launchd や cron から呼ぶ。
#
#   bash daily_run.sh
#
# VOICEVOX ENGINE が止まっていれば起動し、Claude Code に DAILY.md を実行させる。
# 記録は video_state.json に残るので、同じ記事を二度上げない。

set -u

REPO="$HOME/jinja-matching"
ENGINE_DIR="${VOICEVOX_DIR:-$HOME/macos-arm64}"
HOST="${VOICEVOX_HOST:-http://127.0.0.1:50021}"
LOG_DIR="$REPO/logs"
LOG="$LOG_DIR/$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"
exec >>"$LOG" 2>&1
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 開始 ====="

cd "$REPO" || { echo "リポジトリがありません: $REPO"; exit 1; }

# 1. VOICEVOX ENGINE を用意する
if curl -sS -m 5 "$HOST/version" >/dev/null 2>&1; then
  echo "VOICEVOX は起動済み"
else
  if [ ! -x "$ENGINE_DIR/run" ]; then
    echo "VOICEVOX ENGINE が見つかりません: $ENGINE_DIR/run"
    exit 1
  fi
  echo "VOICEVOX を起動します"
  (cd "$ENGINE_DIR" && nohup ./run --host 127.0.0.1 --port 50021 >"$LOG_DIR/engine.log" 2>&1 &)
  for _ in $(seq 1 40); do
    sleep 3
    if curl -sS -m 5 "$HOST/version" >/dev/null 2>&1; then break; fi
  done
  if ! curl -sS -m 5 "$HOST/version" >/dev/null 2>&1; then
    echo "VOICEVOX が起動しませんでした。$LOG_DIR/engine.log を確認してください"
    exit 1
  fi
  echo "VOICEVOX 起動完了"
  STARTED_ENGINE=1
fi

# 2. 仮想環境
if [ -f "$REPO/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  . "$REPO/.venv/bin/activate"
else
  echo ".venv がありません。先に作成してください"
  exit 1
fi

# 3. 残りがあるか確認してから走らせる
if ! python3 pick_article.py --status; then
  echo "処理できる記事がありません"
  exit 0
fi

# 4. Claude Code に DAILY.md を実行させる
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.claude/local/claude}"
if [ ! -x "$CLAUDE_BIN" ]; then
  CLAUDE_BIN="$(command -v claude || true)"
fi
if [ -z "$CLAUDE_BIN" ]; then
  echo "claude コマンドが見つかりません"
  exit 1
fi

"$CLAUDE_BIN" -p "DAILY.md を読んで、今日の1本を最後まで実行して。途中で判断に迷ったら中断し、何が起きたかを説明すること。" \
  --permission-mode acceptEdits
STATUS=$?

echo "----- Claude 終了コード: $STATUS -----"
python3 pick_article.py --status

# 起動したエンジンはそのままにしておく（次回の起動時間を節約するため）。
# 止めたい場合は次の行のコメントを外す。
# [ "${STARTED_ENGINE:-0}" = "1" ] && pkill -f "$ENGINE_DIR/run"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 終了 ====="
exit $STATUS

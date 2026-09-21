#!/usr/bin/env bash
# 毎日1本を無人で作ってアップロードする。launchd や cron から呼ぶ。
#
#   bash daily_run.sh
#
# 決まりきった処理はこのスクリプトが直接行い、Claude には台本を書く工程だけを
# 任せる。そのため Claude に Bash の実行権限を与える必要がない。

set -u

REPO="$HOME/jinja-matching"
SITE="${DENEN_SITE:-$HOME/Downloads/denenseikatu-site}"
ENGINE_DIR="${VOICEVOX_DIR:-$HOME/macos-arm64}"
HOST="${VOICEVOX_HOST:-http://127.0.0.1:50021}"
LOG_DIR="$REPO/logs"
LOG="$LOG_DIR/$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"
exec >>"$LOG" 2>&1
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 開始 ====="

cd "$REPO" || { echo "リポジトリがありません: $REPO"; exit 1; }

die() { echo "中断: $*"; exit 1; }

# --- 1. VOICEVOX ENGINE ---------------------------------------------------
if curl -sS -m 5 "$HOST/version" >/dev/null 2>&1; then
  echo "VOICEVOX は起動済み"
else
  [ -x "$ENGINE_DIR/run" ] || die "VOICEVOX ENGINE がありません: $ENGINE_DIR/run"
  echo "VOICEVOX を起動します"
  (cd "$ENGINE_DIR" && nohup ./run --host 127.0.0.1 --port 50021 >"$LOG_DIR/engine.log" 2>&1 &)
  for _ in $(seq 1 40); do
    sleep 3
    curl -sS -m 5 "$HOST/version" >/dev/null 2>&1 && break
  done
  curl -sS -m 5 "$HOST/version" >/dev/null 2>&1 \
    || die "VOICEVOX が起動しませんでした。$LOG_DIR/engine.log を確認してください"
  echo "VOICEVOX 起動完了"
fi

# --- 2. 仮想環境 ----------------------------------------------------------
[ -f "$REPO/.venv/bin/activate" ] || die ".venv がありません"
# shellcheck disable=SC1091
. "$REPO/.venv/bin/activate"

# --- 3. 今日の記事を選ぶ --------------------------------------------------
PICK="$(python3 pick_article.py --site "$SITE")" || die "記事を選べませんでした"
echo "$PICK"
SLUG="$(printf '%s\n' "$PICK" | awk '/^スラッグ:/{print $2}')"
ARTICLE_PATH="$(printf '%s\n' "$PICK" | awk '/^パス:/{print $2}')"
[ -n "$SLUG" ] && [ -n "$ARTICLE_PATH" ] || die "記事の特定に失敗しました"

# --- 4. 抽出 --------------------------------------------------------------
python3 extract_article.py "$ARTICLE_PATH" -o article.json || die "抽出に失敗しました"

# --- 5. 台本づくり（ここだけ Claude に任せる）-----------------------------
# Bash は使わせない。article.json を読んで script.json を書くだけ。
rm -f script.json
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.claude/local/claude}"
[ -x "$CLAUDE_BIN" ] || CLAUDE_BIN="$(command -v claude || true)"
[ -n "$CLAUDE_BIN" ] || die "claude コマンドが見つかりません"

"$CLAUDE_BIN" -p "article.json と prompts/narration.md を読み、narration.md のルールに従って script.json を書いてください。

- 書式の見本は examples/script.sample.json（内容は流用しない）
- source_url と site、site_host は article.json の値をそのまま使う
- speaker は 10
- youtube ブロックのタイトル・概要欄・タグも記事の内容で書く
- 概要欄には、一般的な参考情報であり医師の診断・治療に代わるものではない旨を入れる

健康・運動・栄養の記事です。narration.md の「数値とデータの扱い」「研究・出典の扱い」を必ず守ってください。記事にある数値だけを使い、主張の強さを変えず、記事にない健康上の助言を足さないこと。

script.json を書く以外のことはしないでください。" \
  --permission-mode acceptEdits \
  --allowedTools "Read" "Write" "Edit" "Glob" "Grep" \
  || die "台本の作成に失敗しました"

[ -f script.json ] || die "script.json が作られませんでした"
python3 -c "
import json, sys
d = json.load(open('script.json'))
for k in ('title', 'source_url', 'speaker', 'scenes'):
    if k not in d:
        sys.exit(f'script.json に {k} がありません')
if '$SLUG' not in d['source_url']:
    sys.exit('script.json の source_url が今日の記事と一致しません: ' + d['source_url'])
if not d['scenes']:
    sys.exit('scenes が空です')
print(f\"台本 OK: {len(d['scenes'])} スライド\")
" || die "script.json の検証に失敗しました"

# --- 6. 書き出し ----------------------------------------------------------
python3 build_video.py script.json -o out/ || die "動画の書き出しに失敗しました"
[ -f out/video.mp4 ] || die "out/video.mp4 がありません"

# --- 7. アップロード ------------------------------------------------------
# 公開設定は PRIVACY で変えられる。public にすると人目に触れるので、
# 台本の出来を確認したうえで運用すること。
PRIVACY="${PRIVACY:-public}"
UP="$(python3 upload_youtube.py out/video.mp4 --privacy "$PRIVACY")" \
  || die "アップロードに失敗しました"
echo "$UP"
URL="$(printf '%s\n' "$UP" | awk '/^完了:/{print $2}')"
[ -n "$URL" ] || die "動画URLを取得できませんでした"

# --- 8. 記録 --------------------------------------------------------------
python3 pick_article.py --done "$SLUG" --url "$URL" || die "記録に失敗しました"
echo "完了: $SLUG → $URL"
python3 pick_article.py --site "$SITE" --status

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 終了 ====="

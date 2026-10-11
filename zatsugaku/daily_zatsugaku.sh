#!/usr/bin/env bash
# 暮らしと健康の雑学動画（約3分）を毎日1本作って YouTube にアップロードする。launchd から呼ぶ。
#
#   bash ~/jinja-matching/zatsugaku/daily_zatsugaku.sh
#
# 台本を書く工程だけ Claude に任せ、出典の確認（WebFetch）も Claude が行う。
# それ以外（検査・絵の取得・書き出し・アップロード・記録）はこのスクリプトが行う。
#
# 音声: VOICEVOX（青山龍星）で固定（2026-10-01 オーナー判断）。
# 公開設定: PRIVACY（既定 public。2026-10-01 オーナー指示）。
#
# Mac がスリープなどで作れなかった日は、クラウドのルーティン（cloud_zatsugaku.sh）が代わりに作る。
# どちらが作るかは GitHub の zatsugaku-state ブランチの台帳で決める（先に担当を取った方が作る）。

set -u

DIR="$HOME/jinja-matching/zatsugaku"
REPO="$HOME/jinja-matching"
ENGINE_DIR="${VOICEVOX_DIR:-$HOME/macos-arm64}"
HOST="${VOICEVOX_HOST:-http://127.0.0.1:50021}"
TODAY="$(TZ=Asia/Tokyo date +%F)"
SCRIPT="scripts/$TODAY.json"
OUT="out/$TODAY"
LOG_DIR="$DIR/logs"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$LOG_DIR"
exec >>"$LOG_DIR/$TODAY.log" 2>&1
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 開始 ====="
cd "$DIR" || { echo "ディレクトリがありません: $DIR"; exit 1; }
# 失敗の理由は台帳にも残す（クラウドが読んで報告できるように）
die() { echo "中断: $*"; python3 zatsugaku_state.py release --by mac --reason "$*" >/dev/null 2>&1; exit 1; }

# 最新版のスクリプトを取ってきて、取れたら入れ替えてやり直す（直した内容が Mac にも自動で届くように）
if [ -z "${ZATSUGAKU_UPDATED:-}" ]; then
  BR=claude/denen-video-pipeline-myltss
  if git -C "$REPO" pull -q --ff-only origin "$BR"; then
    echo "最新版を取得しました"
  elif git -C "$REPO" fetch -q origin "$BR"; then
    # Mac が作って投稿できなかった台本と、クラウドが代わりに作って保存した同じ日付の台本がぶつかると
    # 取り込みが止まる。ぶつかる手元の台本だけ ~/zatsugaku_backup に退避してやり直す
    bak="$HOME/zatsugaku_backup/$(date +%Y%m%d-%H%M%S)"
    git -C "$REPO" ls-files --others --exclude-standard -- zatsugaku/scripts | while read -r f; do
      git -C "$REPO" cat-file -e "FETCH_HEAD:$f" 2>/dev/null && mkdir -p "$bak" && mv "$REPO/$f" "$bak/" && echo "退避: $f → $bak"
    done
    if git -C "$REPO" pull -q --ff-only origin "$BR"; then
      echo "最新版を取得しました（ぶつかった台本を退避）"
    else
      echo "注意: 最新版を取得できませんでした（手元の版で続けます）"
    fi
  else
    echo "注意: 最新版を取得できませんでした（手元の版で続けます）"
  fi
  export ZATSUGAKU_UPDATED=1
  exec bash "$DIR/daily_zatsugaku.sh" "$@"
fi

# shellcheck disable=SC1091
[ -f "$DIR/.env" ] && set -a && . "$DIR/.env" && set +a
PRIVACY="${PRIVACY:-public}"

# YouTube の許可: 合言葉（~/.unlock_pass）があれば、クラウドと共通の暗号化した許可（cloud/secrets.enc）を使う。
# 許可を取り直すのはクラウド側の1か所で済み、Mac の許可が切れて止まることがなくなる
if [ -f "$HOME/.unlock_pass" ] && bash "$REPO/cloud/unlock.sh" "$(cat "$HOME/.unlock_pass")" >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  . "$HOME/.video_env"
  echo "YouTube の許可: クラウドと共通のものを使います"
fi

# 今日の担当を取る。投稿済みか、クラウドが作成中なら何もしない
python3 zatsugaku_state.py claim --by mac
code=$?
[ "$code" -eq 3 ] && { echo "===== 終了（今日は不要）====="; exit 0; }
[ "$code" -eq 0 ] || { echo "中断: 台帳を確認できませんでした"; exit 1; }
python3 zatsugaku_state.py pull || die "台帳を取得できませんでした"
# 台本や書き出しに時間をかける前に、YouTube の許可が生きているか確かめる
# （切れていたらすぐ手放し、クラウドの予備に回す）
( . "$REPO/.venv/bin/activate" && cd "$REPO" && python3 yt_auth.py check ) \
  || die "YouTube の認証に失敗しました（許可の期限切れの可能性。yt_auth.py check を参照）"
THEME="$(python3 zatsugaku_state.py theme)" || die "今日のテーマを決められませんでした"
SCOPE="$(python3 zatsugaku_state.py theme --scope)"
echo "今日のテーマ: $SCOPE"

# --- 1. 音声エンジン ------------------------------------------------------
if curl -sS -m 5 "$HOST/version" >/dev/null 2>&1; then
  echo "音声: VOICEVOX（起動済み）"
else
  [ -x "$ENGINE_DIR/run" ] || die "VOICEVOX ENGINE がありません: $ENGINE_DIR/run"
  (cd "$ENGINE_DIR" && nohup ./run --host 127.0.0.1 --port 50021 >"$LOG_DIR/engine.log" 2>&1 &)
  for _ in $(seq 1 40); do sleep 3; curl -sS -m 5 "$HOST/version" >/dev/null 2>&1 && break; done
  curl -sS -m 5 "$HOST/version" >/dev/null 2>&1 || die "VOICEVOX が起動しませんでした"
  echo "音声: VOICEVOX（起動しました）"
fi

# --- 2. 台本（Claude）。検査に落ちたら指摘を渡して2回まで書き直させる ------
CLAUDE_BIN="$(command -v claude || echo "$HOME/.local/bin/claude")"
[ -x "$CLAUDE_BIN" ] || die "claude コマンドが見つかりません"

if [ ! -f "$SCRIPT" ]; then
  "$CLAUDE_BIN" -p "prompts/zatsugaku.md のルールに従って、今日（$TODAY）の雑学動画の台本を $SCRIPT に書いてください。

- **今日のテーマは「$THEME」。10個すべてこのテーマの雑学にする**（台本の theme と各 category も「$THEME」）
- テーマの範囲: $SCOPE。prompts/zatsugaku.md にこのテーマ向けの注意があれば必ず守る

- 見本は scripts/trial_01.json（文体と書式だけ参考にし、内容は流用しない）
- state.json の used_topics と used_sources にある話題・出典は使わない
- 10個すべて、論文の要旨か公的資料を WebFetch で実際に開いて数値を確かめてから書く。確かめられなかった雑学は入れない
- 調べものと執筆は自分で行う（ほかのエージェントに任せない）。ネタ探しには WebSearch を使ってよい
- $SCRIPT を書く以外のことはしないでください" \
    --permission-mode acceptEdits \
    --allowedTools "Read" "Write" "Edit" "Glob" "Grep" "WebFetch" "WebSearch" \
    || die "台本の作成に失敗しました"
fi
# 今日のテーマでネタが10個そろわないと Claude が判断したら（scripts/<日付>.skip）、
# 台帳でテーマを次に切り替えて、1回だけ書き直しを頼む
SKIP="scripts/$TODAY.skip"
if [ -f "$SKIP" ] && [ ! -f "$SCRIPT" ]; then
  echo "「$THEME」は10個そろわない: $(cat "$SKIP")"
  rm -f "$SKIP"
  python3 zatsugaku_state.py skip-theme || die "テーマを切り替えられませんでした"
  THEME="$(python3 zatsugaku_state.py theme)"
  SCOPE="$(python3 zatsugaku_state.py theme --scope)"
  "$CLAUDE_BIN" -p "prompts/zatsugaku.md のルールに従って、今日（$TODAY）の雑学動画の台本を $SCRIPT に書いてください。

- **今日のテーマは「$THEME」。10個すべてこのテーマの雑学にする**（台本の theme と各 category も「$THEME」）。前のテーマでは10個そろわなかったため切り替えた
- テーマの範囲: $SCOPE。prompts/zatsugaku.md にこのテーマ向けの注意があれば必ず守る
- 見本は scripts/trial_01.json（文体と書式だけ参考にし、内容は流用しない）
- state.json の used_topics と used_sources にある話題・出典は使わない
- 10個すべて、論文の要旨か公的資料を WebFetch で実際に開いて数値を確かめてから書く
- 調べものと執筆は自分で行う（ほかのエージェントに任せない）。ネタ探しには WebSearch を使ってよい
- $SCRIPT を書く以外のことはしないでください" \
    --permission-mode acceptEdits \
    --allowedTools "Read" "Write" "Edit" "Glob" "Grep" "WebFetch" "WebSearch" \
    || die "台本の作成に失敗しました"
fi
[ -f "$SCRIPT" ] || die "$SCRIPT が作られませんでした"

for attempt in 1 2; do
  CHECK="$(python3 zatsugaku_state.py check "$SCRIPT")" && break
  echo "$CHECK"
  "$CLAUDE_BIN" -p "$SCRIPT が台本の検査に落ちました。prompts/zatsugaku.md のルールを守って、次の指摘だけを直してください。直すために新しい雑学に差し替える場合は、その出典も WebFetch で確かめてください。

$CHECK" \
    --permission-mode acceptEdits \
    --allowedTools "Read" "Write" "Edit" "Glob" "Grep" "WebFetch" "WebSearch" \
    || die "台本の修正に失敗しました"
done
python3 zatsugaku_state.py check "$SCRIPT" || die "台本の検査に通りませんでした"

# --- 3. 絵（いらすとや） --------------------------------------------------
python3 fetch_irasutoya.py "$SCRIPT" || die "絵の取得に失敗しました"

# --- 4. 書き出し ----------------------------------------------------------
python3 build_zatsugaku.py "$SCRIPT" -o "$OUT" --engine voicevox || die "動画の書き出しに失敗しました"
[ -f "$OUT/video.mp4" ] || die "$OUT/video.mp4 がありません"
python3 -c "import json,sys; d=json.load(open('$OUT/meta.json'))['duration']; print(f'尺 {d:.1f}秒'); sys.exit(0 if 150 <= d <= 215 else 1)" \
  || die "尺が想定外です。台本の分量を確認してください"

# --- 5. アップロード ------------------------------------------------------
# shellcheck disable=SC1091
. "$REPO/.venv/bin/activate"
UP="$(cd "$REPO" && python3 upload_youtube.py "zatsugaku/$OUT/video.mp4" \
        --script "zatsugaku/$OUT/upload.json" --privacy "$PRIVACY" --no-chapters)" \
  || die "アップロードに失敗しました"
echo "$UP"
URL="$(printf '%s\n' "$UP" | awk '/^完了:/{print $2}')"
[ -n "$URL" ] || die "動画URLを取得できませんでした"

# --- 6. 記録 --------------------------------------------------------------
python3 zatsugaku_state.py done "$SCRIPT" --url "$URL" --by mac \
  || { echo "注意: 台帳への記録に失敗しました（動画は公開済み）: $URL"; exit 1; }
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 終了（$PRIVACY）====="

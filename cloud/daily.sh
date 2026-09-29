#!/usr/bin/env bash
# クラウド版の毎日1本。Mac を使わない。ルーティンのセッションから呼ぶ。
#
#   bash cloud/daily.sh prepare   # 準備・記事選び・抽出 → article.json
#   （ここでセッションが prompts/narration.md に従って script.json を書く）
#   bash cloud/daily.sh publish   # 検証・書き出し・アップロード
#
# 処理済みの判断は YouTube の投稿済み動画（概要欄の記事URL）で行う。台帳ファイルは使わない。
# 必要な環境変数: YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN（yt_auth.py 参照）
#                 GEMINI_API_KEY（台本の voice が gemini のとき）
#
# STYLE（既定 talking）:
#   talking       アニメ調の語り手がスクリーンの横で口を動かして話す形式（build_talking.py）
#   presentation  実写風の語り手の6ポーズが各スライドで説明する形式（build_presentation.py）
#   slides        スライドのみ（build_video.py・VOICEVOX）
# 声は台本の "voice" で決まる。{"engine": "gemini", ...} なら Gemini（VOICEVOX は起動しない）

set -u
cd "$(dirname "$0")/.." || exit 1

SITEMAP="${DENEN_SITEMAP:-https://denenseikatu.com/sitemap.xml}"
PRIVACY="${PRIVACY:-public}"
TODAY_FILE=".today_slug"
STYLE="${STYLE:-talking}"
GEMINI_VOICE="${GEMINI_VOICE:-1}"   # 1 なら Gemini の声を使う前提で準備する（VOICEVOX を起動しない）
DRY="${DRY:-0}"          # 1 にすると送信せず、投稿済みの確認も飛ばす（試験用）

# 各段階の結果を routine-log ブランチに書き残す（自動実行のセッションの中身は外から
# 読めないため、失敗したときに何が起きたかを後から確かめられるようにする）
LOG_FILE="$HOME/.routine_log.txt"
log() {
  printf '%s %s\n' "$(TZ=Asia/Tokyo date '+%m/%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}
push_log() {
  [ "$DRY" = "1" ] && return 0
  local tmp; tmp="$(mktemp -d)"
  ( cd "$tmp" && git init -q && git checkout -q -b routine-log && cp "$LOG_FILE" log.txt \
    && git add log.txt && git -c user.name=denen-video -c user.email=noreply@anthropic.com \
       commit -q -m "自動実行の記録" && git push -q -f "$ORIGIN_URL" routine-log ) >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap push_log EXIT

die() { log "中断: $*"; exit 1; }

# Gemini の1日の無料枠を使い切ったとき、台本と途中までの音声を GitHub のブランチに預け、
# 翌日の実行で続きから作る（自動実行は毎回まっさらな環境で動くため、手元には残らない）
PENDING_BRANCH="video-pending"
PENDING_DIR="$HOME/.video_pending"
ORIGIN_URL="$(git remote get-url origin)"

save_pending() {
  local slug="$1"
  rm -rf "$PENDING_DIR" && mkdir -p "$PENDING_DIR/audio"
  cp script.json "$PENDING_DIR/"
  printf '%s\n' "$slug" >"$PENDING_DIR/slug"
  cp out/audio/*.wav "$PENDING_DIR/audio/" 2>/dev/null || true
  if ( cd "$PENDING_DIR" && git init -q && git checkout -q -b "$PENDING_BRANCH" \
       && git add -A && git -c user.name=denen-video -c user.email=noreply@anthropic.com \
          commit -q -m "作りかけの動画: $slug" \
       && git push -q -f "$ORIGIN_URL" "$PENDING_BRANCH" ); then
    echo "途中までの台本と音声を $PENDING_BRANCH に保存しました（$slug）"
  else
    echo "注意: 途中までの音声を保存できませんでした。翌日は最初から作り直します"
  fi
}

clear_pending() {
  # ブランチを消せない環境があるので、中身のない状態で上書きする
  local tmp; tmp="$(mktemp -d)"
  ( cd "$tmp" && git init -q && git checkout -q -b "$PENDING_BRANCH" \
    && git -c user.name=denen-video -c user.email=noreply@anthropic.com \
       commit -q --allow-empty -m "作りかけの動画なし" \
    && git push -q -f "$ORIGIN_URL" "$PENDING_BRANCH" ) >/dev/null 2>&1 || true
  rm -rf "$tmp"
}

restore_pending() {
  # 作りかけがあれば script.json と音声を戻し、その記事のスラッグを出す
  local tmp; tmp="$(mktemp -d)"
  if ! git clone -q --depth 1 -b "$PENDING_BRANCH" "$ORIGIN_URL" "$tmp" 2>/dev/null; then
    rm -rf "$tmp"; return 1
  fi
  if [ ! -f "$tmp/slug" ] || [ ! -f "$tmp/script.json" ]; then
    rm -rf "$tmp"; return 1
  fi
  cp "$tmp/script.json" script.json
  mkdir -p out/audio && cp "$tmp"/audio/*.wav out/audio/ 2>/dev/null || true
  cat "$tmp/slug"
  rm -rf "$tmp"
}

prepare() {
  : >"$LOG_FILE"
  log "prepare 開始（STYLE=$STYLE）"
  if [ "$GEMINI_VOICE" = "1" ]; then
    bash cloud/setup.sh --no-engine || die "依存の準備に失敗しました"
    [ -n "${GEMINI_API_KEY:-}" ] || die "GEMINI_API_KEY がありません"
  else
    bash cloud/setup.sh || die "VOICEVOX / 依存の準備に失敗しました"
  fi
  python3 yt_auth.py check || die "YouTube の認証に失敗しました"

  # 日本時間の今日すでに記事動画を上げていれば、二重投稿を避けて終わる
  PICK="$(python3 pick_article.py --sitemap "$SITEMAP" --youtube --once-per-day)"
  code=$?
  echo "$PICK"
  [ "$code" -eq 3 ] && { log "SKIP: 日本時間の今日は投稿済み"; echo "SKIP"; exit 3; }
  [ "$code" -eq 0 ] || die "記事を選べませんでした"

  # 前日に無料枠を使い切って作りかけになった動画があれば、その続きから作る
  rm -rf out
  PENDING_SLUG="$(restore_pending || true)"
  if [ -n "$PENDING_SLUG" ]; then
    if python3 -c "import sys; from pick_article import youtube_done; sys.exit(0 if sys.argv[1] in youtube_done() else 1)" "$PENDING_SLUG"; then
      echo "作りかけの記事はすでに投稿済みなので破棄します: $PENDING_SLUG"
      rm -rf out script.json
      clear_pending
    else
      printf '%s\n' "$PENDING_SLUG" >"$TODAY_FILE"
      n=$(ls out/audio/*.wav 2>/dev/null | wc -l)
      log "RESUME: $PENDING_SLUG（音声 ${n} 件を引き継ぎ）"
      echo "RESUME: $PENDING_SLUG（台本と音声 ${n} 文を前日から引き継ぎました。台本は書き直さず、そのまま publish すること）"
      exit 0
    fi
  fi

  SLUG="$(printf '%s\n' "$PICK" | awk '/^スラッグ:/{print $2}')"
  URL="$(printf '%s\n' "$PICK" | awk '/^URL:/{print $2}')"
  [ -n "$SLUG" ] && [ -n "$URL" ] || die "記事の特定に失敗しました"
  printf '%s\n' "$SLUG" >"$TODAY_FILE"

  rm -f script.json
  python3 extract_article.py "$URL" -o article.json --dump || die "抽出に失敗しました"
  log "READY: $SLUG（抽出まで完了。次は台本）"
  echo "READY: $SLUG"
}

publish() {
  [ -f "$TODAY_FILE" ] || die "先に prepare を実行してください"
  SLUG="$(cat "$TODAY_FILE")"
  log "publish 開始: $SLUG"
  [ -f script.json ] || die "script.json がありません"

  python3 - "$SLUG" "$STYLE" <<'PY' || die "script.json の検証に失敗しました"
import json, sys
slug, style = sys.argv[1], sys.argv[2]
d = json.load(open("script.json", encoding="utf-8"))
uses_voice = style in ("presentation", "talking") and "voice" in d
for k in ("title", "source_url", "voice" if uses_voice or style == "presentation" else "speaker",
          "scenes", "youtube"):
    if k not in d:
        sys.exit(f"script.json に {k} がありません")
if f"/articles/{slug}/" not in d["source_url"]:
    sys.exit(f"source_url が今日の記事と一致しません: {d['source_url']}")
if not d["scenes"]:
    sys.exit("scenes が空です")
for s in d["scenes"]:
    for line in s.get("lines", []):
        if len(line) > 60:
            sys.exit(f"60文字を超える文があります（scene {s.get('id')}）: {line}")
if style == "presentation":
    need = {"title": ["heading"], "closing": ["heading"], "screen": ["heading", "bullets"],
            "bullets": ["heading", "bullets"], "checklist": ["heading", "bullets"],
            "number": ["heading", "number"], "table": ["heading", "rows"],
            "compare": ["heading", "left", "right"], "steps": ["heading", "steps"]}
    for i, s in enumerate(d["scenes"], 1):
        lay = s.get("layout", "bullets")
        if lay not in need:
            sys.exit(f"scene {i}: 未知の layout です: {lay}")
        for k in need[lay] + ["lines"]:
            if not s.get(k):
                sys.exit(f"scene {i}（{lay}）に {k} がありません")
if style == "talking":
    for i, s in enumerate(d["scenes"], 1):
        for k in ("heading", "lines"):
            if not s.get(k):
                sys.exit(f"scene {i} に {k} がありません")
        if len(s.get("bullets", [])) > 5:
            sys.exit(f"scene {i}: bullets は5項目までにしてください（スクリーンに収まらない）")
if style in ("presentation", "talking") and "voice" in d:
    if d["voice"].get("engine") != "gemini":
        sys.exit('voice は {"engine": "gemini", ...} にしてください')
    if not d["youtube"].get("synthetic"):
        sys.exit("youtube.synthetic を true にしてください（AI の音声を申告するため）")
print(f"台本 OK: {len(d['scenes'])} スライド")
PY

  # 書き出しのあいだに別経路（Mac など）で上がっていないか、送信直前にもう一度確かめる
  [ "$DRY" = "1" ] || python3 - "$SLUG" <<'PY' || die "投稿済みの確認に失敗しました"
import sys
from pick_article import youtube_done
done = youtube_done()
if sys.argv[1] in done:
    sys.exit(f"この記事はすでに投稿済みです: {done[sys.argv[1]]['url']}")
PY

  # 合成済みの音声（out/audio）は残す。途中で失敗して publish をやり直しても、
  # Gemini の回数を二重に使わない。音声を捨てるのは prepare で記事を選び直したとき
  rm -rf out/slides out/frames out/video.mp4
  case "$STYLE" in
    presentation) python3 build_presentation.py script.json -o out/ ;;
    talking)      python3 build_talking.py script.json -o out/ ;;
    slides)       python3 build_video.py script.json -o out/ ;;
    *)            die "未知の STYLE です: $STYLE" ;;
  esac
  code=$?
  if [ "$code" -eq 75 ]; then
    [ "$DRY" = "1" ] || save_pending "$SLUG"
    log "QUOTA: 今日の無料枠を使い切り。途中まで保存して明日に回す（$SLUG）"
    echo "QUOTA: Gemini の今日の無料枠を使い切りました。明日の枠で続きを作ってアップします。"
    exit 75
  fi
  [ "$code" -eq 0 ] || die "動画の書き出しに失敗しました"
  [ -f out/video.mp4 ] || die "out/video.mp4 がありません"
  # 雑音（無音から急な大音量・音割れ）が残っていたらアップしない
  python3 check_audio.py out/video.mp4 || die "音声に雑音が残っているためアップを中止しました"

  if [ "$DRY" = "1" ]; then
    python3 upload_youtube.py out/video.mp4 --privacy "$PRIVACY" --dry-run
    return
  fi
  UP="$(python3 upload_youtube.py out/video.mp4 --privacy "$PRIVACY")" || die "アップロードに失敗しました"
  echo "$UP"
  log "公開: $(printf '%s\n' "$UP" | grep -E '^完了:|^公開設定:' | tr '\n' ' ')"
  rm -f "$TODAY_FILE"
  clear_pending
}

case "${1:-}" in
  prepare) prepare ;;
  publish) publish ;;
  note)    shift; log "メモ: $*" ;;     # 台本づくりなど、daily.sh の外の段階の結果を残す
  *) echo "使い方: bash cloud/daily.sh prepare|publish"; exit 1 ;;
esac

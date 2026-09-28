#!/usr/bin/env bash
# クラウド版の毎日1本。Mac を使わない。ルーティンのセッションから呼ぶ。
#
#   bash cloud/daily.sh prepare   # 準備・記事選び・抽出 → article.json
#   （ここでセッションが prompts/narration.md に従って script.json を書く）
#   bash cloud/daily.sh publish   # 検証・書き出し・アップロード
#
# 処理済みの判断は YouTube の投稿済み動画（概要欄の記事URL）で行う。台帳ファイルは使わない。
# 必要な環境変数: YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN（yt_auth.py 参照）
#                 GEMINI_API_KEY（STYLE=presentation のとき。Gemini の声を使う）
#
# STYLE（既定 presentation）:
#   presentation  語り手の6ポーズが各スライドで説明する形式（build_presentation.py・Gemini の声）
#   talking       アニメ調の語り手が口を動かす形式（build_talking.py・VOICEVOX）
#   slides        スライドのみ（build_video.py・VOICEVOX）

set -u
cd "$(dirname "$0")/.." || exit 1

SITEMAP="${DENEN_SITEMAP:-https://denenseikatu.com/sitemap.xml}"
PRIVACY="${PRIVACY:-public}"
TODAY_FILE=".today_slug"
STYLE="${STYLE:-presentation}"
DRY="${DRY:-0}"          # 1 にすると送信せず、投稿済みの確認も飛ばす（試験用）

die() { echo "中断: $*"; exit 1; }

prepare() {
  if [ "$STYLE" = "presentation" ]; then
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
  [ "$code" -eq 3 ] && { echo "SKIP"; exit 3; }
  [ "$code" -eq 0 ] || die "記事を選べませんでした"

  SLUG="$(printf '%s\n' "$PICK" | awk '/^スラッグ:/{print $2}')"
  URL="$(printf '%s\n' "$PICK" | awk '/^URL:/{print $2}')"
  [ -n "$SLUG" ] && [ -n "$URL" ] || die "記事の特定に失敗しました"
  printf '%s\n' "$SLUG" >"$TODAY_FILE"

  rm -f script.json
  python3 extract_article.py "$URL" -o article.json --dump || die "抽出に失敗しました"
  echo "READY: $SLUG"
}

publish() {
  [ -f "$TODAY_FILE" ] || die "先に prepare を実行してください"
  SLUG="$(cat "$TODAY_FILE")"
  [ -f script.json ] || die "script.json がありません"

  python3 - "$SLUG" "$STYLE" <<'PY' || die "script.json の検証に失敗しました"
import json, sys
slug, style = sys.argv[1], sys.argv[2]
d = json.load(open("script.json", encoding="utf-8"))
for k in ("title", "source_url", "voice" if style == "presentation" else "speaker",
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
    if d.get("voice", {}).get("engine") != "gemini":
        sys.exit('voice は {"engine": "gemini", ...} にしてください')
    if not d["youtube"].get("synthetic"):
        sys.exit("youtube.synthetic を true にしてください（AI の人物と音声を申告するため）")
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

  if [ "$DRY" = "1" ]; then
    rm -rf out/slides out/frames out/video.mp4    # 試験では合成済みの音声を使い回す
  else
    rm -rf out
  fi
  case "$STYLE" in
    presentation) python3 build_presentation.py script.json -o out/ ;;
    talking)      python3 build_talking.py script.json -o out/ ;;
    slides)       python3 build_video.py script.json -o out/ ;;
    *)            die "未知の STYLE です: $STYLE" ;;
  esac || die "動画の書き出しに失敗しました"
  [ -f out/video.mp4 ] || die "out/video.mp4 がありません"

  if [ "$DRY" = "1" ]; then
    python3 upload_youtube.py out/video.mp4 --privacy "$PRIVACY" --dry-run
    return
  fi
  python3 upload_youtube.py out/video.mp4 --privacy "$PRIVACY" || die "アップロードに失敗しました"
  rm -f "$TODAY_FILE"
}

case "${1:-}" in
  prepare) prepare ;;
  publish) publish ;;
  *) echo "使い方: bash cloud/daily.sh prepare|publish"; exit 1 ;;
esac

#!/usr/bin/env bash
# クラウド版の毎日1本。Mac を使わない。ルーティンのセッションから呼ぶ。
#
#   bash cloud/daily.sh prepare   # 準備・記事選び・抽出 → article.json
#   （ここでセッションが prompts/narration.md に従って script.json を書く）
#   bash cloud/daily.sh publish   # 検証・書き出し・アップロード
#
# 処理済みの判断は YouTube の投稿済み動画（概要欄の記事URL）で行う。台帳ファイルは使わない。
# 必要な環境変数: YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN（yt_auth.py 参照）

set -u
cd "$(dirname "$0")/.." || exit 1

SITEMAP="${DENEN_SITEMAP:-https://denenseikatu.com/sitemap.xml}"
PRIVACY="${PRIVACY:-public}"
TODAY_FILE=".today_slug"

die() { echo "中断: $*"; exit 1; }

prepare() {
  bash cloud/setup.sh || die "VOICEVOX / 依存の準備に失敗しました"
  python3 yt_auth.py check || die "YouTube の認証に失敗しました"

  # 直近20時間以内に記事動画を上げていれば二重投稿を避けて終わる
  PICK="$(python3 pick_article.py --sitemap "$SITEMAP" --youtube --skip-if-within 20)"
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

  python3 - "$SLUG" <<'PY' || die "script.json の検証に失敗しました"
import json, sys
slug = sys.argv[1]
d = json.load(open("script.json", encoding="utf-8"))
for k in ("title", "source_url", "speaker", "scenes", "youtube"):
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
print(f"台本 OK: {len(d['scenes'])} スライド")
PY

  # 書き出しのあいだに別経路（Mac など）で上がっていないか、送信直前にもう一度確かめる
  python3 - "$SLUG" <<'PY' || die "投稿済みの確認に失敗しました"
import sys
from pick_article import youtube_done
done = youtube_done()
if sys.argv[1] in done:
    sys.exit(f"この記事はすでに投稿済みです: {done[sys.argv[1]]['url']}")
PY

  rm -rf out
  python3 build_video.py script.json -o out/ || die "動画の書き出しに失敗しました"
  [ -f out/video.mp4 ] || die "out/video.mp4 がありません"

  python3 upload_youtube.py out/video.mp4 --privacy "$PRIVACY" || die "アップロードに失敗しました"
  rm -f "$TODAY_FILE"
}

case "${1:-}" in
  prepare) prepare ;;
  publish) publish ;;
  *) echo "使い方: bash cloud/daily.sh prepare|publish"; exit 1 ;;
esac

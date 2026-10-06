#!/usr/bin/env bash
# 雑学動画のクラウド版（Mac がスリープなどで作れなかった日の予備）。ルーティンのセッションから呼ぶ。
#
#   bash zatsugaku/cloud_zatsugaku.sh prepare   # 台帳の確認・担当取り・VOICEVOX と素材の準備
#   （ここでセッションが prompts/zatsugaku.md に従って scripts/<日付>.json を書き、
#     python3 zatsugaku/zatsugaku_state.py check で検査に通す）
#   bash zatsugaku/cloud_zatsugaku.sh publish   # 絵の取得・書き出し・アップロード・記録
#   bash zatsugaku/cloud_zatsugaku.sh release   # 途中で諦めたとき担当を手放す
#
# 毎日の2本目（追加の回。クラウドだけが作る。Mac の1本目とは記録先のキーが別なので重ならない）:
#   bash zatsugaku/cloud_zatsugaku.sh extra-prepare [外すテーマ,…]  # 記録先（日付-extraN）とテーマを決める
#   （ここでセッションが scripts/<日付-extraN>.json を書き、check --theme <テーマ> で検査に通す）
#   bash zatsugaku/cloud_zatsugaku.sh extra-publish                  # 書き出し・アップロード・記録
#
# 終了コード 3 = 今日は投稿済みか Mac が作成中なので何もしない。
# 必要な環境変数: YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN（cloud/unlock.sh が用意する）

set -u
cd "$(dirname "$0")" || exit 1
REPO="$(cd .. && pwd)"
TODAY="$(TZ=Asia/Tokyo date +%F)"
SCRIPT="scripts/$TODAY.json"
OUT="out/$TODAY"
PRIVACY="${PRIVACY:-public}"

die() { echo "中断: $*"; python3 zatsugaku_state.py release --by cloud >/dev/null 2>&1; exit 1; }

prepare() {
  python3 zatsugaku_state.py claim --by cloud
  code=$?
  [ "$code" -eq 3 ] && { echo "SKIP"; exit 3; }
  [ "$code" -eq 0 ] || die "台帳を確認できませんでした"
  python3 zatsugaku_state.py pull || die "台帳を取得できませんでした"
  (cd "$REPO" && bash cloud/setup.sh) || die "VOICEVOX / 依存の準備に失敗しました"
  python3 fetch_assets.py || die "素材（BGM・フォント・絵）の準備に失敗しました"
  (cd "$REPO" && python3 yt_auth.py check) || die "YouTube の認証に失敗しました"
  THEME="$(python3 zatsugaku_state.py theme)" || die "今日のテーマを決められませんでした"
  SCOPE="$(python3 zatsugaku_state.py theme --scope)"
  echo "READY: zatsugaku/$SCRIPT を書いてください。今日のテーマは「$THEME」で、10個すべてこのテーマにする。テーマの範囲: $SCOPE。prompts/zatsugaku.md にこのテーマ向けの注意があれば必ず守る（見本 scripts/trial_01.json）。このテーマで過去回と重ならない確かめられた雑学が10個そろわなければ、作り話で埋めず \`cd zatsugaku && python3 zatsugaku_state.py skip-theme\` を実行し、表示された新しいテーマで書き直す"
}

publish() {
  [ -f "$SCRIPT" ] || die "$SCRIPT がありません"
  python3 zatsugaku_state.py check "$SCRIPT" || die "台本の検査に通っていません。直してから publish してください"
  python3 fetch_irasutoya.py "$SCRIPT" || die "絵の取得に失敗しました"
  python3 build_zatsugaku.py "$SCRIPT" -o "$OUT" --engine voicevox || die "動画の書き出しに失敗しました"
  python3 -c "import json,sys; d=json.load(open('$OUT/meta.json'))['duration']; print(f'尺 {d:.1f}秒'); sys.exit(0 if 150 <= d <= 215 else 1)" \
    || die "尺が想定外です。台本の分量を確認してください"
  # 書き出しのあいだに Mac が上げていないか、送信直前にもう一度確かめる
  python3 zatsugaku_state.py claim --by cloud >/dev/null
  [ $? -eq 3 ] && { echo "SKIP: 書き出しのあいだに Mac が投稿しました"; exit 3; }
  UP="$(cd "$REPO" && python3 upload_youtube.py "zatsugaku/$OUT/video.mp4" \
          --script "zatsugaku/$OUT/upload.json" --privacy "$PRIVACY" --no-chapters)" \
    || die "アップロードに失敗しました"
  echo "$UP"
  URL="$(printf '%s\n' "$UP" | awk '/^完了:/{print $2}')"
  [ -n "$URL" ] || die "動画URLを取得できませんでした"
  python3 zatsugaku_state.py done "$SCRIPT" --url "$URL" --by cloud || echo "注意: 台帳への記録に失敗しました（動画は公開済み）: $URL"
  echo "PUBLISHED: $URL"
}

EXTRA_FILE=".extra_today"   # 2本目の「キー<TAB>テーマ」（.gitignore 済みの out/ と同じく手元だけ）

extra_prepare() {
  python3 zatsugaku_state.py pull || die_plain "台帳を取得できませんでした"
  (cd "$REPO" && bash cloud/setup.sh) || die_plain "VOICEVOX / 依存の準備に失敗しました"
  python3 fetch_assets.py || die_plain "素材（BGM・フォント・絵）の準備に失敗しました"
  (cd "$REPO" && python3 yt_auth.py check) || die_plain "YouTube の認証に失敗しました"
  out="$(python3 zatsugaku_state.py extra --skip "${1:-}")" || die_plain "テーマを決められませんでした"
  key="$(printf '%s\n' "$out" | sed -n 1p)"; theme="$(printf '%s\n' "$out" | sed -n 2p)"
  printf '%s\t%s\n' "$key" "$theme" >"$EXTRA_FILE"
  scope="$(python3 -c "import sys; sys.path.insert(0,'.'); import zatsugaku_state as z; print(z.THEME_SCOPE['$theme'])")"
  echo "EXTRA: zatsugaku/scripts/$key.json を書いてください。テーマは「$theme」（範囲: $scope）で、10個すべてこのテーマにする。"
  echo "検査: (cd zatsugaku && python3 zatsugaku_state.py check scripts/$key.json --theme $theme)"
  echo "10個そろわなければ作り話で埋めず: bash zatsugaku/cloud_zatsugaku.sh extra-prepare $theme  （次のテーマに切り替わる。外すテーマはカンマ区切りで足していく）"
}

extra_publish() {
  [ -f "$EXTRA_FILE" ] || die_plain "先に extra-prepare を実行してください"
  key="$(cut -f1 "$EXTRA_FILE")"; theme="$(cut -f2 "$EXTRA_FILE")"
  script="scripts/$key.json"; out="out/$key"
  [ -f "$script" ] || die_plain "$script がありません"
  python3 zatsugaku_state.py check "$script" --theme "$theme" || die_plain "台本の検査に通っていません"
  python3 fetch_irasutoya.py "$script" || die_plain "絵の取得に失敗しました"
  python3 build_zatsugaku.py "$script" -o "$out" --engine voicevox || die_plain "動画の書き出しに失敗しました"
  python3 -c "import json,sys; d=json.load(open('$out/meta.json'))['duration']; print(f'尺 {d:.1f}秒'); sys.exit(0 if 150 <= d <= 215 else 1)" \
    || die_plain "尺が想定外です。台本の分量を確認してください"
  UP="$(cd "$REPO" && python3 upload_youtube.py "zatsugaku/$out/video.mp4" \
          --script "zatsugaku/$out/upload.json" --privacy "$PRIVACY" --no-chapters)" \
    || die_plain "アップロードに失敗しました"
  echo "$UP"
  URL="$(printf '%s\n' "$UP" | awk '/^完了:/{print $2}')"
  [ -n "$URL" ] || die_plain "動画URLを取得できませんでした"
  python3 zatsugaku_state.py done "$script" --url "$URL" --by cloud --key "$key" \
    || echo "注意: 台帳への記録に失敗しました（動画は公開済み）: $URL"
  rm -f "$EXTRA_FILE"
  echo "PUBLISHED: $URL"
}

die_plain() { echo "中断: $*"; exit 1; }

case "${1:-}" in
  prepare) prepare ;;
  publish) publish ;;
  extra-prepare) extra_prepare "${2:-}" ;;
  extra-publish) extra_publish ;;
  release) python3 zatsugaku_state.py release --by cloud ;;
  *) echo "使い方: bash zatsugaku/cloud_zatsugaku.sh prepare|publish|release|extra-prepare|extra-publish"; exit 1 ;;
esac

#!/usr/bin/env bash
# 雑学動画のクラウド版。ルーティンのセッションから呼ぶ。
# 2026-10-17 から、雑学は1日1本・30分以上（体づくりの日とペットの日を交互）。クラウドだけが作る（Mac は作らない）。
#
#   bash zatsugaku/cloud_zatsugaku.sh prepare   # 台帳の確認・担当取り・素材の準備
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
# 必要な環境変数: YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN / GEMINI_API_KEY（cloud/unlock.sh が用意する）
# 形式: 2026-10-17 から記事動画と同じ形式（語り手・Gemini の Leda の声・雑学の BGM）。build_zatsugaku_talking.py

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
  WHY="$(python3 zatsugaku_state.py why 2>/dev/null)"
  [ -n "$WHY" ] && echo "MAC_FAILED: $WHY"
  (cd "$REPO" && bash cloud/setup.sh --no-engine) || die "依存の準備に失敗しました"
  python3 fetch_assets.py || die "素材（BGM・フォント・絵）の準備に失敗しました"
  (cd "$REPO" && python3 yt_auth.py check) || die "YouTube の認証に失敗しました"
  # 2026-10-17 から、雑学は1日1本・30分以上（体づくりの日とペットの日を交互）。章ごとにテーマを分ける
  PLAN="$(python3 zatsugaku_state.py long)" || die "今日の章を決められませんでした"
  KIND="$(printf '%s\n' "$PLAN" | sed -n 1p)"
  echo "READY: zatsugaku/$SCRIPT を書いてください。今日は30分以上の長い雑学動画（種類「$KIND」）を1本作る。"
  echo "  台本の最上位に \"format\": \"long\" と \"theme\": \"$KIND\" を書き、雑学を章（テーマ）ごとに続けて並べる（各雑学の category が章のテーマ）。"
  echo "  合計 96個以上・読み上げ 11,500〜15,500字。1つずつの雑学の書き方・出典の確かめ方・使用済みの話題の扱いは prompts/zatsugaku.md のとおり（「30分以上の長い回」の節も読む）。"
  echo "  章（テーマ・最低の個数・範囲）:"
  printf '%s\n' "$PLAN" | sed -n '2,$p' | awk -F'\t' '{printf "    - %s（%s個以上）: %s\n", $1, $2, $3}'
  echo "  ある章でネタがそろわなければ、作り話で埋めず、その章を予備のテーマ（体づくり: 暮らし／ペット: ペットの暮らし）に替えてよい。"
}

publish() {
  [ -f "$SCRIPT" ] || die "$SCRIPT がありません"
  python3 zatsugaku_state.py check "$SCRIPT" || die "台本の検査に通っていません。直してから publish してください"
  python3 build_zatsugaku_talking.py "$SCRIPT" -o "$OUT" || die "動画の書き出しに失敗しました"
  # 長い回は30分以上、短い回（以前の形式）は約3〜5分
  python3 -c "import json,sys; d=json.load(open('$OUT/meta.json'))['duration']; long=json.load(open('$SCRIPT')).get('format')=='long'; print(f'尺 {d:.1f}秒'); sys.exit(0 if ((1800 <= d <= 4200) if long else (150 <= d <= 330)) else 1)" \
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
  # 2026-10-17 から、雑学は1日1本・30分以上にまとめた（体とペットは日替わり）。2本目は作らない
  if [[ "$TODAY" > "2026-10-16" ]]; then
    echo "SKIP: 雑学は1日1本（30分以上）にまとめたため、2本目は作りません（今日の1本は cloud_zatsugaku.sh prepare で作る）"
    exit 3
  fi
  python3 zatsugaku_state.py pull || die_plain "台帳を取得できませんでした"
  (cd "$REPO" && bash cloud/setup.sh --no-engine) || die_plain "依存の準備に失敗しました"
  python3 fetch_assets.py || die_plain "素材（BGM・フォント・絵）の準備に失敗しました"
  (cd "$REPO" && python3 yt_auth.py check) || die_plain "YouTube の認証に失敗しました"
  out="$(python3 zatsugaku_state.py extra --skip "${1:-}")" || die_plain "テーマを決められませんでした"
  key="$(printf '%s\n' "$out" | sed -n 1p)"; theme="$(printf '%s\n' "$out" | sed -n 2p)"
  printf '%s\t%s\n' "$key" "$theme" >"$EXTRA_FILE"
  scope="$(python3 -c "import sys,json; sys.path.insert(0,'.'); import zatsugaku_state as z; print(z.scope_for(json.load(open('state.json')), '$theme'))")"
  echo "EXTRA: zatsugaku/scripts/$key.json を書いてください。テーマは「$theme」（範囲: $scope）で、10個すべてこのテーマにする。"
  echo "検査: (cd zatsugaku && python3 zatsugaku_state.py check scripts/$key.json --theme $theme)"
  echo "10個そろわなければ作り話で埋めず: bash zatsugaku/cloud_zatsugaku.sh extra-prepare $theme  （次のテーマに切り替わる。外すテーマはカンマ区切りで足していく）"
}

extra_publish() {
  if [[ "$TODAY" > "2026-10-16" ]]; then
    echo "SKIP: 雑学は1日1本（30分以上）にまとめたため、2本目は作りません"
    exit 3
  fi
  [ -f "$EXTRA_FILE" ] || die_plain "先に extra-prepare を実行してください"
  key="$(cut -f1 "$EXTRA_FILE")"; theme="$(cut -f2 "$EXTRA_FILE")"
  script="scripts/$key.json"; out="out/$key"
  [ -f "$script" ] || die_plain "$script がありません"
  python3 zatsugaku_state.py check "$script" --theme "$theme" || die_plain "台本の検査に通っていません"
  python3 build_zatsugaku_talking.py "$script" -o "$out" || die_plain "動画の書き出しに失敗しました"
  python3 -c "import json,sys; d=json.load(open('$out/meta.json'))['duration']; print(f'尺 {d:.1f}秒'); sys.exit(0 if 150 <= d <= 330 else 1)" \
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

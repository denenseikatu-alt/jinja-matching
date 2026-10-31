#!/usr/bin/env bash
# 週1回（日曜）のふりかえり動画（10分以上）。ルーティンのセッションから呼ぶ。
#
#   bash cloud/weekly_review.sh prepare   # 今週の動画の材料 → review_source.json
#   （ここでセッションが prompts/review.md に従って review.json を書く）
#   bash cloud/weekly_review.sh publish   # 検証・書き出し（動く語り手・Gemini の声）・アップロード
#
# 今週分を投稿済みなら prepare が終了コード 3 で終わる。記事動画（script.json・out/）には触れない。

set -u
cd "$(dirname "$0")/.." || exit 1

# 認証情報（cloud/start.sh が用意する）を読む。コマンドの頭に「. ~/.video_env &&」を付けなくてよい
[ -z "${YT_REFRESH_TOKEN:-}" ] && [ -f "$HOME/.video_env" ] && . "$HOME/.video_env"
PRIVACY="${PRIVACY:-public}"
OUT="out_review"

die() { echo "中断: $*"; exit 1; }

prepare() {
  bash cloud/setup.sh --no-engine >/dev/null || die "依存の準備に失敗しました"
  [ -n "${GEMINI_API_KEY:-}" ] || die "GEMINI_API_KEY がありません"
  python3 yt_auth.py check || die "YouTube の認証に失敗しました"
  python3 cloud/review_source.py review_source.json
  code=$?
  [ "$code" -eq 3 ] && { echo "SKIP"; exit 3; }
  [ "$code" -eq 0 ] || die "材料を集められませんでした"
  rm -rf "$OUT" review.json
  echo "READY: prompts/review.md に従って review.json を書いてください（材料 review_source.json、見本 talk/40s-safe-aerobic-talking.json）"
}

publish() {
  [ -f review.json ] || die "review.json がありません"
  python3 - <<'PY' || die "review.json の検証に失敗しました"
import json, sys
d = json.load(open("review.json", encoding="utf-8"))
src = json.load(open("review_source.json", encoding="utf-8"))
for k in ("title", "voice", "scenes", "youtube"):
    if k not in d:
        sys.exit(f"review.json に {k} がありません")
if d["voice"].get("engine") != "gemini" or not d["youtube"].get("synthetic"):
    sys.exit('voice は gemini、youtube.synthetic は true にしてください')
if not d["youtube"].get("title", "").startswith(src["mark"] + "｜"):
    sys.exit(f"youtube.title は「{src['mark']}｜」で始めてください")
for w in ("育つ", "重い重さ"):
    if w in d["youtube"]["title"]:
        sys.exit(f"題名に「{w}」があります（「発達する」「高重量」と書く）")
total = 0
for i, s in enumerate(d["scenes"], 1):
    if not s.get("heading") or not s.get("lines"):
        sys.exit(f"scene {i} に heading か lines がありません")
    if len(s.get("bullets", [])) > 5:
        sys.exit(f"scene {i}: bullets は5項目まで")
    for line in s["lines"]:
        if len(line) > 60:
            sys.exit(f"60文字を超える文があります（scene {i}）: {line}")
        total += len(line)
if not 4000 <= total <= 4800:
    sys.exit(f"読み上げの合計が {total} 字です（4,000〜4,800字で10分以上にする）")
tail = d["scenes"][-2:]
if not any("denenseikatu.com" in s.get("heading", "") + "".join(s.get("bullets", [])) for s in tail):
    sys.exit("最後のシーンのスクリーンに denenseikatu.com を出してください")
if not any(k in line for s in tail for line in s["lines"] for k in ("ドットコム", "denenseikatu")):
    sys.exit("最後のシーンで田園生活のサイト（でんえんせいかつドットコム）を紹介してください")
if d.get("site_host") != "denenseikatu.com":
    sys.exit("site_host を denenseikatu.com にしてください")
print(f"台本 OK: {len(d['scenes'])} 場面・読み上げ {total} 字")
PY
  python3 build_talking.py review.json -o "$OUT/"
  code=$?
  [ "$code" -eq 75 ] && die "Gemini の回数の上限に達しました（音声は $OUT/audio に残っています。publish をやり直すと続きから作ります）"
  [ "$code" -eq 0 ] || die "動画の書き出しに失敗しました"
  python3 - "$OUT/video.mp4" <<'PY' || die "尺が10分に届きません。review.json の分量を増やしてください"
import subprocess, sys, imageio_ffmpeg
r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", sys.argv[1]], capture_output=True, text=True)
import re
h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr).groups()
d = int(h) * 3600 + int(m) * 60 + float(s)
print(f"尺 {int(d // 60)}分{d % 60:04.1f}秒")
sys.exit(0 if d >= 600 else 1)
PY
  python3 check_audio.py "$OUT/video.mp4" || die "音声に雑音が残っているためアップを中止しました"
  python3 cloud/review_source.py /dev/null >/dev/null
  [ $? -eq 3 ] && { echo "SKIP: 今週のふりかえりはすでに投稿されています"; exit 3; }
  python3 upload_youtube.py "$OUT/video.mp4" -s review.json --privacy "$PRIVACY" || die "アップロードに失敗しました"
}

case "${1:-}" in
  prepare) prepare ;;
  publish) publish ;;
  *) echo "使い方: bash cloud/weekly_review.sh prepare|publish"; exit 1 ;;
esac

#!/usr/bin/env bash
# 手撮りの猫の動画のまとめ（2）: clips-work ブランチの plan.json どおりに、まとめ動画とショートを書き出して
# YouTube に「非公開」で上げる。オーナーが YouTube で見て OK なら、Claude が公開に切り替える。
#
#   bash ~/jinja-matching/clips/mac_render.sh
set -eu
REPO="$HOME/jinja-matching"
cd "$REPO"
git pull -q --ff-only origin claude/denen-video-pipeline-myltss || echo "注意: 最新版を取得できませんでした（手元の版で続けます）"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone -q --depth 1 -b clips-work "$(git remote get-url origin)" "$TMP/b"
[ -f "$TMP/b/plan.json" ] || { echo "plan.json がまだありません。Claude に場面選びを頼んでください"; exit 1; }
(cd zatsugaku && "$PY" fetch_assets.py >/dev/null) || echo "注意: BGM を取れませんでした（BGM なしで書き出します）"
rm -rf clips/out
"$PY" clips/render_clips.py "$TMP/b/plan.json" --inbox clips/inbox -o clips/out
# YouTube の許可: クラウドと共通のもの
if [ -f "$HOME/.unlock_pass" ] && bash cloud/unlock.sh "$(cat "$HOME/.unlock_pass")" >/dev/null 2>&1; then
  . "$HOME/.video_env"
fi
for d in clips/out/*/; do
  "$PY" upload_youtube.py "$d/video.mp4" --script "$d/upload.json" --privacy private --no-chapters
done
echo "完了: 非公開で上げました。YouTube Studio の「コンテンツ」で見て、よければ Claude に「公開して」と伝えてください。"

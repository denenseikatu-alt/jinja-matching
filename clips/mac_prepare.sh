#!/usr/bin/env bash
# 手撮りの猫の動画のまとめ（1）: clips/inbox の動画から場面選び用の一覧の絵を作り、GitHub の clips-work ブランチに置く。
# 元の動画は Mac から出さない（置くのは小さな一覧の絵と音の大きさだけ）。
#
#   bash ~/jinja-matching/clips/mac_prepare.sh
#
# このあと、クラウドの Claude が一覧の絵を見て場面を選び、plan.json を clips-work ブランチに置く。
set -eu
REPO="$HOME/jinja-matching"
cd "$REPO"
git pull -q --ff-only origin claude/denen-video-pipeline-myltss || echo "注意: 最新版を取得できませんでした（手元の版で続けます）"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
mkdir -p clips/inbox
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
"$PY" clips/make_sheets.py clips/inbox "$TMP/work"
git clone -q --depth 1 -b clips-work "$(git remote get-url origin)" "$TMP/b" 2>/dev/null || {
  mkdir -p "$TMP/b" && cd "$TMP/b" && git init -q && git checkout -q -b clips-work \
    && git remote add origin "$(cd "$REPO" && git remote get-url origin)"; }
cd "$TMP/b"
mkdir -p work && cp "$TMP"/work/* work/
git add work
git -c user.name=denen-clips -c user.email=noreply@anthropic.com commit -q -m "場面選び用の一覧: $(ls "$TMP/work" | grep -c '\.jpg$') 本" || true
git push -q origin clips-work
echo "完了: 一覧の絵を送りました。Claude に「一覧を送った」と伝えてください。"

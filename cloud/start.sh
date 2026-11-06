#!/usr/bin/env bash
# 毎朝の作業の最初の準備（セッション開始時のフックからも自動で呼ばれる。何度実行してもよい）。
#  1. 作業ブランチを GitHub の最新にそろえる（新しい作業場所では main から作られていることがあるため）
#  2. 認証情報 ~/.video_env を用意する。合言葉は環境変数 VIDEO_UNLOCK_PASS か ~/.unlock_pass から読み、
#     コマンドには書かない（コマンドに合言葉を書くと、作業場所の安全確認で止められる）
#  3. Python の部品がそろっているか確かめ、足りなければ入れる
#
#   bash cloud/start.sh          # 合言葉が見つからなければ終了コード 4
#   bash cloud/start.sh --hook   # フック用。失敗しても止めない

set -u
cd "$(dirname "$0")/.." || exit 1
BRANCH="claude/denen-video-pipeline-myltss"
HOOK=0; [ "${1:-}" = "--hook" ] && HOOK=1
say() { echo "[準備] $*"; }
fail() { say "$1"; [ "$HOOK" = 1 ] && exit 0; exit "${2:-1}"; }

# 1. ブランチ
if git fetch -q origin "$BRANCH" main 2>/dev/null; then
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    say "変更中のファイルがあるため、ブランチはそのままにします"
  else
    [ "$(git rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] || git checkout -q "$BRANCH" 2>/dev/null \
      || git checkout -q -b "$BRANCH" "origin/$BRANCH"
    if git merge-base --is-ancestor HEAD "origin/$BRANCH"; then
      git merge -q --ff-only "origin/$BRANCH"
    elif [ -z "$(git rev-list HEAD --not "origin/$BRANCH" origin/main)" ]; then
      # 手元にあるのが main の履歴だけなら、作業ブランチの最新に置きかえても失うものはない
      git reset -q --hard "origin/$BRANCH"
      say "ブランチを origin/$BRANCH にそろえました"
    else
      say "注意: 手元だけのコミットがあるため、自動ではそろえません（git log origin/$BRANCH..HEAD を確認）"
    fi
  fi
else
  say "注意: GitHub から最新を取れませんでした"
fi

# 2. 認証情報
if [ ! -s "$HOME/.video_env" ]; then
  if [ -n "${VIDEO_UNLOCK_PASS:-}" ] || [ -s "$HOME/.unlock_pass" ]; then
    bash cloud/unlock.sh >/dev/null || fail "合言葉が違うため、認証情報を用意できませんでした"
    say "認証情報を用意しました"
  else
    fail "合言葉が見つかりません（環境変数 VIDEO_UNLOCK_PASS も ~/.unlock_pass もありません）" 4
  fi
fi

# 3. Python の部品
if ! python3 -c "import google.auth, googleapiclient, cv2, PIL, numpy" 2>/dev/null; then
  bash cloud/setup.sh --no-engine >/dev/null 2>&1 || fail "Python の部品を入れられませんでした"
  python3 -c "import google.auth, googleapiclient, cv2" 2>/dev/null || fail "Python の部品が足りません"
  say "Python の部品を入れました"
fi
say "OK"

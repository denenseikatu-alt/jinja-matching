#!/usr/bin/env bash
# 暗号化した認証情報（cloud/secrets.enc）を解いて ~/.video_env に書く。
# 合言葉は環境変数 VIDEO_UNLOCK_PASS（作業場所の設定に保存）か ~/.unlock_pass から読む。
# コマンドに合言葉を直接書かない（作業場所の安全確認で止められ、作業ログにも残る）。リポジトリにも置かない。
#
#   bash cloud/unlock.sh            # ふつうはこれ（cloud/start.sh が自動で呼ぶ）
#   bash cloud/unlock.sh '<合言葉>'   # 古い使い方。使わない
#
# secrets.enc の作り方（YT_* と GEMINI_API_KEY の export 行を暗号化する）:
#   openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -a -pass file:<合言葉のファイル> \
#     -in <平文> -out cloud/secrets.enc

set -eu
cd "$(dirname "$0")/.."
if [ $# -ge 1 ]; then
  pass="$1"
elif [ -n "${VIDEO_UNLOCK_PASS:-}" ]; then
  pass="$VIDEO_UNLOCK_PASS"
elif [ -s "$HOME/.unlock_pass" ]; then
  pass="$(cat "$HOME/.unlock_pass")"
else
  echo "合言葉がありません（環境変数 VIDEO_UNLOCK_PASS か ~/.unlock_pass に置く）"; exit 4
fi

umask 077
out="$HOME/.video_env"
printf '%s' "$pass" | openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -a -pass stdin \
  -in cloud/secrets.enc -out "$out" || { rm -f "$out"; echo "合言葉が違います"; exit 1; }
cat >>"$out" <<'EOF'
# 2026-10-20 オーナー了承: lite の1日100回を使い切ったら、同じ Leda の声のまま gemini-3.8-flash-tts（別に1日100回）に切り替える
# （全サイト紹介動画は声をそろえるため、コマンドの前に GEMINI_TTS_MODEL=gemini-3.8-flash-lite-tts を付けて lite だけで作る）
export GEMINI_TTS_MODEL=gemini-3.8-flash-lite-tts,gemini-3.8-flash-tts
export STYLE=talking
EOF
echo "認証情報を $out に書きました"

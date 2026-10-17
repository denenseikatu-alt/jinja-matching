#!/usr/bin/env bash
# 暗号化した認証情報（cloud/secrets.enc）を解いて ~/.video_env に書く。
# 合言葉はルーティンの指示文にだけ書く（リポジトリには置かない）。
#
#   bash cloud/unlock.sh '<合言葉>'
#   . ~/.video_env && bash cloud/daily.sh prepare
#
# secrets.enc の作り方（YT_* と GEMINI_API_KEY の export 行を暗号化する）:
#   openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -a -pass file:<合言葉のファイル> \
#     -in <平文> -out cloud/secrets.enc

set -eu
cd "$(dirname "$0")/.."
[ $# -eq 1 ] || { echo "使い方: bash cloud/unlock.sh '<合言葉>'"; exit 1; }

umask 077
out="$HOME/.video_env"
printf '%s' "$1" | openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -a -pass stdin \
  -in cloud/secrets.enc -out "$out" || { rm -f "$out"; echo "合言葉が違います"; exit 1; }
cat >>"$out" <<'EOF'
export GEMINI_TTS_MODEL=gemini-3.8-flash-lite-tts
export STYLE=talking
EOF
echo "認証情報を $out に書きました"

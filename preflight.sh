#!/usr/bin/env bash
# 動画パイプラインを動かす前の環境チェック。
# 足りないものを洗い出して、直し方まで出す。
#   bash preflight.sh

set -u
NG=0
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
ng()   { printf '  \033[31mNG\033[0m   %s\n' "$1"; NG=1; }
info() { printf '       %s\n' "$1"; }

echo "== 動画パイプライン 事前チェック =="

# Python
if command -v python3 >/dev/null 2>&1; then
  ok "python3 $(python3 -V 2>&1 | awk '{print $2}')"
else
  ng "python3 が見つかりません"
  info "https://www.python.org/downloads/ から入れてください"
fi

# Pillow
if python3 -c "import PIL" 2>/dev/null; then
  ok "Pillow"
else
  ng "Pillow が入っていません"
  info "pip3 install pillow"
fi

# ffmpeg
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg ($(command -v ffmpeg))"
elif python3 -c "import imageio_ffmpeg" 2>/dev/null; then
  ok "ffmpeg (imageio-ffmpeg 同梱)"
else
  ng "ffmpeg が見つかりません"
  info "pip3 install imageio-ffmpeg   # または brew install ffmpeg"
fi

# 日本語フォント
FONT=$(python3 - <<'PY' 2>/dev/null
import sys
sys.path.insert(0, ".")
try:
    import build_video
    print(build_video.find_font())
except SystemExit:
    pass
except Exception:
    pass
PY
)
if [ -n "$FONT" ]; then
  ok "日本語フォント: $FONT"
else
  ng "日本語フォントが見つかりません"
  info "build_video.py に --font でパスを直接指定してください"
fi

# VOICEVOX
HOST="${VOICEVOX_HOST:-http://127.0.0.1:50021}"
if curl -sS -m 5 "$HOST/version" >/dev/null 2>&1; then
  VER=$(curl -sS -m 5 "$HOST/version" 2>/dev/null | tr -d '"')
  ok "VOICEVOX ENGINE $VER ($HOST)"
  SPK=$(curl -sS -m 10 "$HOST/speakers" 2>/dev/null | python3 -c "
import json,sys
try:
    for sp in json.load(sys.stdin):
        for st in sp.get('styles', []):
            if st.get('id') == 10:
                print(f\"{sp['name']} / {st['name']}\")
except Exception:
    pass
" 2>/dev/null)
  if [ -n "$SPK" ]; then
    ok "話者ID 10 = $SPK"
    info "この名前が概要欄のクレジットになります。意図と違えば話者IDを見直してください"
  else
    ng "話者ID 10 が見つかりません"
    info "$HOST/speakers を開いて、使いたい声のIDを確認してください"
  fi
else
  ng "VOICEVOX ENGINE に接続できません ($HOST)"
  info "VOICEVOX を起動してください。別ポートなら VOICEVOX_HOST=... を指定"
fi

# YouTube 認証（アップロードする場合のみ）
if [ -f token.json ]; then
  ok "YouTube 認証済み (token.json)"
elif [ -f client_secret.json ]; then
  ok "client_secret.json あり（初回実行時にブラウザで認可）"
else
  info "-- YouTube にアップロードしない場合は不要 --"
  info "client_secret.json が未設置です（アップロード時のみ必要）"
fi

echo
if [ "$NG" -eq 0 ]; then
  echo "すべて揃っています。VIDEO.md の手順に進めます。"
else
  echo "上の NG を解消してから実行してください。"
  exit 1
fi

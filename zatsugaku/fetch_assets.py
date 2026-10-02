#!/usr/bin/env python3
"""雑学動画に要る素材をその場で取ってくる。何度実行してもよい（あるものは取り直さない）。

    python3 fetch_assets.py

- BGM: もっぴーさうんど「Escort」（OpenTracks 旧DOVA-SYNDROME）。音源単体の再配布は規約で
  禁止なので、リポジトリには入れず配布元から毎回取る。
- 導入と締めの絵（いらすとや）。いらすとやの絵もリポジトリには入れない。
- フォント: Mac はヒラギノを使う。無い環境（クラウドの Linux）では Noto Sans JP を取る。
"""

from __future__ import annotations

import http.cookiejar
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BGM = HERE / "assets" / "bgm" / "escort.mp3"
IMG_DIR = HERE / "assets" / "irasutoya"
FONT = HERE / "assets" / "fonts" / "NotoSansJP.ttf"
HIRAGINO = Path("/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc")

UA = {"User-Agent": "Mozilla/5.0"}
BGM_PAGE = "https://opentracks.com/bgm/detail/12633/download"
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf"
_B = "https://blogger.googleusercontent.com/img/b/R29vZ2xl/"
FIXED_IMAGES = {
    "hirameki_man.png": _B + "AVvXsEiThh51O_5PBczGCVOAZqWk0NniNOu2Fxun8BlELAmHwR8Rltl1Gnqb_u0dkHvf34yGijTLvwnjWDAe6f-LtgOXAiX3sj__yCp5rsa2KTeaR0uaGye3zKUaTCUd8PiHDAObRfDSW8JT9qc/s800/hirameki_man.png",
    "uroko_man.png": _B + "AVvXsEjFX-N0UWszoyKRRVxOjkkNpubUT370UX68cjHOxhQ_rR_GVNNsWpGLwJLUX5kQQrNuMzaHhvnPIsJstFk5ucLY4NtqYlZM2s178Nr83n2zOqo44VLmKh5B25gXRy9Soi6c9Nvjg9c25gvk/s800/kotowaza_mekara_uroko_man.png",
}


def fetch_bgm() -> None:
    if BGM.exists() and BGM.stat().st_size > 1_000_000:
        return
    BGM.parent.mkdir(parents=True, exist_ok=True)
    jar = http.cookiejar.CookieJar()

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    plain = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    page = plain.open(urllib.request.Request(BGM_PAGE, headers=UA), timeout=60).read().decode("utf-8", "ignore")
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page)
    if not token:
        sys.exit("BGM の配布ページの形が変わっています: " + BGM_PAGE)
    data = urllib.parse.urlencode({"csrfmiddlewaretoken": token.group(1), "track": "1"}).encode()
    no_redirect = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)
    try:
        no_redirect.open(urllib.request.Request(BGM_PAGE, data=data, headers={**UA, "Referer": BGM_PAGE}), timeout=60)
        sys.exit("BGM のダウンロード先が返ってきませんでした")
    except urllib.error.HTTPError as e:  # 302 で署名つきのダウンロード先が返る
        loc = e.headers.get("Location")
        if e.code not in (301, 302, 303) or not loc:
            raise
    mp3 = urllib.request.urlopen(urllib.request.Request(loc, headers=UA), timeout=120).read()
    if mp3[:3] != b"ID3" and mp3[:2] != b"\xff\xfb":
        sys.exit("BGM の取得結果が mp3 ではありません")
    BGM.write_bytes(mp3)
    print(f"BGM を取得しました（{len(mp3) / 1e6:.1f} MB）")


def fetch_images() -> None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in FIXED_IMAGES.items():
        path = IMG_DIR / name
        if not path.exists():
            path.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read())


def fetch_font() -> None:
    if HIRAGINO.exists() or FONT.exists():
        return
    FONT.parent.mkdir(parents=True, exist_ok=True)
    FONT.write_bytes(urllib.request.urlopen(urllib.request.Request(FONT_URL, headers=UA), timeout=120).read())
    print("フォント（Noto Sans JP）を取得しました")


if __name__ == "__main__":
    fetch_bgm()
    fetch_images()
    fetch_font()
    print("素材の準備 OK")

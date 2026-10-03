#!/usr/bin/env python3
"""YouTube の認証情報を用意する。Mac のブラウザが無い環境（クラウド・スマホ）向け。

認証情報の探し方（load_credentials）:
    1. 環境変数 YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN がそろっていればそれを使う
       （クラウド実行環境の Environment variables に置く想定）
    2. なければ従来どおり token.json / client_secret.json（Mac 用）

初回の認可（スマホでもできる）:
    # 1. 認可URLを出す。YT_CLIENT_ID と YT_CLIENT_SECRET を環境変数で渡すか、
    #    client_secret.json を置いておく
    python3 yt_auth.py url

    # 2. URL をブラウザで開いて許可する。最後に localhost のページが
    #    「開けません」になるが、それでよい。そのときのアドレスバーの URL を丸ごと渡す
    python3 yt_auth.py exchange 'http://localhost:8765/?state=...&code=...'

    → 環境変数に入れる3行が表示される
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# 動画の送信と、送信済み動画の一覧（同じ記事を二度上げないため）に使う
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
# Mac の token.json は upload だけで認可済み。範囲を広げると更新に失敗するので分けておく
LEGACY_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

TOKEN_URI = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://localhost:8765/"
# 認可の途中経過（PKCE の検証子）。リポジトリの外に置く
PENDING = Path.home() / ".yt_auth_pending.json"


def _env_credentials():
    cid = os.environ.get("YT_CLIENT_ID")
    secret = os.environ.get("YT_CLIENT_SECRET")
    refresh = os.environ.get("YT_REFRESH_TOKEN")
    if not (cid and secret and refresh):
        return None
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials(None, refresh_token=refresh, client_id=cid,
                        client_secret=secret, token_uri=TOKEN_URI)
    creds.refresh(Request())
    return creds


def load_credentials(client_secret: Path | None = None, token: Path | None = None):
    """環境変数 → token.json の順で認証情報を返す。どちらも無ければ Mac 用の初回認可に進む。"""
    creds = _env_credentials()
    if creds:
        return creds

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_secret = client_secret or REPO_ROOT / "client_secret.json"
    token = token or REPO_ROOT / "token.json"

    creds = None
    if token.is_file():
        creds = Credentials.from_authorized_user_file(str(token), LEGACY_SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding="utf-8")
        return creds
    if not client_secret.is_file():
        sys.exit(
            "YouTube の認証情報がありません。\n"
            "クラウドでは環境変数 YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN を、\n"
            f"Mac では {client_secret} を用意してください（手順は yt_auth.py の先頭）。"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), LEGACY_SCOPES)
    creds = flow.run_local_server(port=0)
    token.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _client_config() -> dict:
    cid = os.environ.get("YT_CLIENT_ID")
    secret = os.environ.get("YT_CLIENT_SECRET")
    if cid and secret:
        return {"installed": {
            "client_id": cid, "client_secret": secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI, "redirect_uris": ["http://localhost"],
        }}
    path = REPO_ROOT / "client_secret.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    sys.exit("YT_CLIENT_ID と YT_CLIENT_SECRET（または client_secret.json）が必要です。")


def cmd_url() -> None:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), SCOPES, redirect_uri=REDIRECT_URI,
                                   autogenerate_code_verifier=True)
    # refresh_token を確実に受け取るため、毎回同意画面を出す
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    PENDING.write_text(json.dumps({"state": state, "verifier": flow.code_verifier}),
                       encoding="utf-8")
    PENDING.chmod(0o600)
    print(url)


def cmd_exchange(redirected: str) -> None:
    from google_auth_oauthlib.flow import Flow

    if not PENDING.is_file():
        sys.exit("先に `python3 yt_auth.py url` を実行してください。")
    pending = json.loads(PENDING.read_text(encoding="utf-8"))
    flow = Flow.from_client_config(_client_config(), SCOPES, redirect_uri=REDIRECT_URI,
                                   state=pending["state"])
    flow.code_verifier = pending["verifier"]
    # localhost は http だが、ループバックへのリダイレクトなので問題ない
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    flow.fetch_token(authorization_response=redirected.strip())
    creds = flow.credentials
    PENDING.unlink()
    if not creds.refresh_token:
        sys.exit("refresh token が返りませんでした。`url` からやり直してください。")
    cfg = _client_config()["installed"]
    print("環境変数に次の3行を追加してください（他人に見せないこと）:\n")
    print(f"YT_CLIENT_ID={cfg['client_id']}")
    print(f"YT_CLIENT_SECRET={cfg['client_secret']}")
    print(f"YT_REFRESH_TOKEN={creds.refresh_token}")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "url":
        cmd_url()
    elif len(sys.argv) >= 3 and sys.argv[1] == "exchange":
        cmd_exchange(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "check":
        creds = _env_credentials()
        if not creds:
            sys.exit("YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN がそろっていません。")
        from googleapiclient.discovery import build

        ch = build("youtube", "v3", credentials=creds).channels().list(
            part="snippet", mine=True).execute()
        items = ch.get("items", [])
        print("認証 OK: " + (items[0]["snippet"]["title"] if items else "(チャンネルなし)"))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

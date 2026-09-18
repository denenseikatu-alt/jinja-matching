#!/usr/bin/env python3
"""build_video.py が書き出した mp4 を YouTube に非公開でアップロードする。

    python3 upload_youtube.py out/video.mp4

タイトル・概要欄・タグは script.json の "youtube" ブロックから取る。
概要欄の末尾には、記事URL と VOICEVOX のクレジットを自動で付ける。

事前準備:
    pip install google-auth-oauthlib google-api-python-client
    Google Cloud で YouTube Data API v3 を有効にし、
    「デスクトップアプリ」の OAuth クライアントIDを client_secret.json として置く。
    初回実行時にブラウザで認可すると token.json が作られ、次回以降は不要。

注意:
    アップロードは既定で privacyStatus=private（非公開）。
    公開したい場合は script.json の youtube.privacyStatus を変えるか --privacy で指定する。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
REPO_ROOT = Path(__file__).resolve().parent


def build_description(script: dict, outdir: Path, with_chapters: bool) -> str:
    yt = script.get("youtube", {})
    parts = [yt.get("description", "").rstrip()]

    chapters_file = outdir / "chapters.txt"
    if with_chapters and chapters_file.is_file():
        parts.append("■ 目次\n" + chapters_file.read_text(encoding="utf-8").strip())

    source_url = script.get("source_url")
    if source_url:
        parts.append(f"■ 記事\n{source_url}")

    # VOICEVOX はキャラクター名を含むクレジット表記を求めている。
    # build_video.py がエンジンから引いた正式名称を credits.txt に残している。
    credits_file = outdir / "credits.txt"
    credit = credits_file.read_text(encoding="utf-8").strip() if credits_file.is_file() else None
    if not credit or credit == "VOICEVOX":
        sys.exit(
            f"VOICEVOX のキャラクター名が特定できません（{credits_file}）。\n"
            "VOICEVOX ENGINE を起動した状態で build_video.py を実行し直してください。\n"
            "利用規約上、クレジットにはキャラクター名の明記が必要です。"
        )
    parts.append(f"■ 音声\n{credit}")

    return "\n\n".join(p for p in parts if p)


def get_credentials(client_secret: Path, token: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token.is_file():
        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding="utf-8")
        return creds
    if not client_secret.is_file():
        sys.exit(
            f"OAuth クライアント情報がありません: {client_secret}\n"
            "Google Cloud で YouTube Data API v3 を有効にし、デスクトップアプリの\n"
            "クライアントIDを client_secret.json として保存してください。"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0)
    token.write_text(creds.to_json(), encoding="utf-8")
    return creds


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", help="アップロードする mp4")
    ap.add_argument("-s", "--script", default="script.json")
    ap.add_argument("--privacy", choices=["private", "unlisted", "public"], default=None,
                    help="script.json の設定を上書き（既定: private）")
    ap.add_argument("--no-chapters", action="store_true", help="概要欄に目次を入れない")
    ap.add_argument("--client-secret", default="client_secret.json")
    ap.add_argument("--token", default="token.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="送信せず、実際に送る内容だけ表示する")
    args = ap.parse_args()

    video = Path(args.video)
    if not video.is_file():
        sys.exit(f"動画がありません: {video}\n先に build_video.py で書き出してください。")

    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    yt = script.get("youtube")
    if not yt:
        sys.exit(f'{args.script} に "youtube" ブロックがありません。')

    description = build_description(script, video.parent, not args.no_chapters)
    privacy = args.privacy or yt.get("privacyStatus", "private")

    body = {
        "snippet": {
            "title": yt["title"],
            "description": description,
            "tags": yt.get("tags", []),
            "categoryId": yt.get("categoryId", "22"),
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }

    if args.dry_run:
        print(f"--- dry-run: 送信しません（{video}, {video.stat().st_size / 1e6:.1f} MB）---")
        print(f"公開設定: {privacy}")
        print(f"タイトル: {body['snippet']['title']}")
        print(f"タグ: {', '.join(body['snippet']['tags'])}")
        print("--- 概要欄 ---")
        print(description)
        return

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = get_credentials(REPO_ROOT / args.client_secret, REPO_ROOT / args.token)
    youtube = build("youtube", "v3", credentials=creds)

    media = MediaFileUpload(str(video), chunksize=4 * 1024 * 1024, resumable=True,
                            mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"\r送信中 {int(status.progress() * 100)}%", end="", flush=True)

    video_id = response["id"]
    print(f"\n完了: https://www.youtube.com/watch?v={video_id}")
    print(f"公開設定: {privacy}")


if __name__ == "__main__":
    main()

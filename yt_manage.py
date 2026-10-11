#!/usr/bin/env python3
"""公開済みの動画の題名の一括変更と、再生リストの作成・追加。

youtube.force-ssl の許可が要る（yt_auth.py の url → exchange で取り直す）。
既定は「試し」で、何を変えるかを表示するだけ。--apply を付けたときだけ実際に変える。

    # 題名: 表のファイルの「オーナーの確定題名」が埋まっている行だけ、1回に30本まで
    python3 yt_manage.py titles docs/youtube/title_proposals_2026-10.csv [--limit 30] [--apply]

    # 再生リスト: なければ作り、動画を足す（すでに入っている動画は足さない）
    python3 yt_manage.py playlist "猫の一言シリーズ" --desc "..." --ids ID1,ID2 [--apply]
"""

from __future__ import annotations

import argparse
import csv
import sys

from yt_auth import _env_credentials


def _yt():
    from googleapiclient.discovery import build

    creds = _env_credentials()
    if not creds:
        sys.exit("YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN がそろっていません（. ~/.video_env）")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def cmd_titles(path: str, limit: int, apply: bool) -> None:
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8"))
            if r.get("オーナーの確定題名", "").strip()]
    if not rows:
        print("「オーナーの確定題名」が埋まった行がありません")
        return
    yt = _yt()
    done = 0
    for r in rows:
        if done >= limit:
            print(f"今回は {limit} 本で止めます（残りは次回）")
            break
        new = r["オーナーの確定題名"].strip()
        if len(new) > 100:
            print(f"飛ばす（100文字を超える）: {r['id']}")
            continue
        items = yt.videos().list(part="snippet", id=r["id"]).execute().get("items", [])
        if not items:
            print(f"見つからない: {r['id']}")
            continue
        sn = items[0]["snippet"]
        if sn["title"] == new:
            continue
        print(f"{r['id']}: {sn['title']!r} → {new!r}")
        done += 1
        if apply:
            # 題名以外（概要欄・タグ・カテゴリ・言語）はそのまま送り返す
            body = {k: sn[k] for k in ("title", "description", "tags", "categoryId",
                                       "defaultLanguage", "defaultAudioLanguage") if k in sn}
            body["title"] = new
            yt.videos().update(part="snippet", body={"id": r["id"], "snippet": body}).execute()
    print(("変更しました" if apply else "試しのみ（--apply で実際に変更）") + f": {done} 本")


def cmd_playlist(title: str, desc: str, ids: list[str], apply: bool) -> None:
    yt = _yt()
    pl = None
    req = yt.playlists().list(part="snippet", mine=True, maxResults=50)
    while req:
        res = req.execute()
        pl = next((p for p in res["items"] if p["snippet"]["title"] == title), None) or pl
        req = yt.playlists().list_next(req, res)
    if pl is None:
        print(f"再生リストを作る: {title}")
        if not apply:
            print(f"試しのみ: {len(ids)} 本を足す予定")
            return
        pl = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": title, "description": desc},
            "status": {"privacyStatus": "public"}}).execute()
    have = set()
    req = yt.playlistItems().list(part="contentDetails", playlistId=pl["id"], maxResults=50)
    while req:
        res = req.execute()
        have |= {i["contentDetails"]["videoId"] for i in res["items"]}
        req = yt.playlistItems().list_next(req, res)
    add = [i for i in ids if i not in have]
    print(f"{title}: {len(have)} 本入り、{len(add)} 本を足す")
    if apply:
        for vid in add:
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": pl["id"], "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
        print(f"https://www.youtube.com/playlist?list={pl['id']}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("titles")
    t.add_argument("csv")
    t.add_argument("--limit", type=int, default=30)
    t.add_argument("--apply", action="store_true")
    pl = sub.add_parser("playlist")
    pl.add_argument("title")
    pl.add_argument("--desc", default="")
    pl.add_argument("--ids", default="")
    pl.add_argument("--apply", action="store_true")
    a = p.parse_args()
    if a.cmd == "titles":
        cmd_titles(a.csv, a.limit, a.apply)
    else:
        cmd_playlist(a.title, a.desc, [i for i in a.ids.split(",") if i], a.apply)


if __name__ == "__main__":
    main()

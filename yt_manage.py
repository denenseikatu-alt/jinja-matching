#!/usr/bin/env python3
"""公開済みの動画の題名の一括変更と、再生リストの作成・追加。

youtube.force-ssl の許可が要る（yt_auth.py の url → exchange で取り直す）。
既定は「試し」で、何を変えるかを表示するだけ。--apply を付けたときだけ実際に変える。

    # 題名: 表のファイルの「オーナーの確定題名」が埋まっている行だけ、1回に30本まで
    python3 yt_manage.py titles docs/youtube/title_proposals_2026-10.csv [--limit 30] [--apply]

    # 再生リスト: なければ作り、動画を足す（すでに入っている動画は足さない）
    python3 yt_manage.py playlist "猫の一言シリーズ" --desc "..." --ids ID1,ID2 [--apply]

    # 決まった2つの再生リスト（手撮り・雑学）に、まだ入っていない公開動画を再生の多い順に足す
    python3 yt_manage.py sync-playlists [--limit 40] [--apply]

    # 当たった手撮り動画（再生 --min 回以上）の概要欄の一番上に、再生リストへの誘導文を足す（足してあれば飛ばす）
    python3 yt_manage.py promote [--min 1000] [--limit 30] [--apply]

YouTube の1日の操作の枠（10,000）は、日本時間16時に戻る。動画のアップロードは1本1,600、題名の変更と
再生リストへの追加は1回50を使う。毎朝のアップロード（3〜4本）の分を残すため、1日に変えるのは合わせて70回まで。
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
        if sn["title"].strip() != r.get("今の題名", "").strip():
            # オーナーが自分で題名を変えた動画は、案で上書きしない
            print(f"飛ばす（題名がすでに変わっている）: {r['id']} {sn['title']!r}")
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


SERIES = {
    "9割が知らない犬と猫の雑学": "犬と猫の体のしくみや気持ち、一緒に暮らすことと健康の関係を、研究論文で確かめて約3分で紹介します。毎日更新。\n\n田園生活のサイト: https://denenseikatu.com/",
    "9割が知らない体づくりの雑学": "筋トレ・栄養・体づくりの「本当はどうなの？」を、論文で確かめて約3分で紹介します。毎日更新。\n\n田園生活のサイト: https://denenseikatu.com/",
    "猫と旅の一言シリーズ": "旅先やわが家で出会った子たちの、ひと言つきの短い動画です。新しい子に会うたびに足していきます。\n\n田園生活のサイト: https://denenseikatu.com/",
}


PET_WORDS = ("猫の", "犬の", "ペット")
BODY_WORDS = ("筋トレ", "筋肥大", "栄養", "プロテイン", "ビタミン", "持久", "長寿", "体", "ダイエット", "健康")


def kind(title: str, live: bool) -> str:
    if title.startswith("9割が") and any(w in title for w in PET_WORDS):
        return "9割が知らない犬と猫の雑学"
    if title.startswith("9割が"):
        # 体づくりと関係の薄いテーマの回（恋愛・婚活など、10/11 までの回）は入れない
        return "9割が知らない体づくりの雑学" if any(w in title for w in BODY_WORDS) else ""
    if "｜" in title or live or title == "筋トレ　サプリ　栄養について":
        return ""      # 記事動画・ふりかえり・ライブ配信は入れない
    return "猫と旅の一言シリーズ"


def cmd_sync(limit: int, apply: bool) -> None:
    yt = _yt()
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = []
    req = yt.playlistItems().list(part="contentDetails", playlistId=up, maxResults=50)
    while req:
        res = req.execute()
        ids += [i["contentDetails"]["videoId"] for i in res["items"]]
        req = yt.playlistItems().list_next(req, res)
    want: dict[str, list[tuple[int, str]]] = {k: [] for k in SERIES}
    for k in range(0, len(ids), 50):
        for v in yt.videos().list(part="snippet,statistics,status,liveStreamingDetails",
                                  id=",".join(ids[k:k + 50])).execute()["items"]:
            if v["status"]["privacyStatus"] != "public":
                continue
            name = kind(v["snippet"]["title"], "liveStreamingDetails" in v)
            if name:
                want[name].append((int(v["statistics"].get("viewCount", 0)), v["id"]))
    left = limit
    for name, vids in want.items():
        ordered = [vid for _, vid in sorted(vids, reverse=True)]
        left -= cmd_playlist(name, SERIES[name], ordered, apply, left)
        if left <= 0:
            break


PROMO_MARK = "▶ 猫と旅の一言シリーズ（再生リスト）"


def promo_text(playlist_id: str) -> str:
    return ("旅先の景色や、わが家と旅先で出会った子たちの「ひと言」を集めています。\n"
            f"{PROMO_MARK}: https://www.youtube.com/playlist?list={playlist_id}\n"
            "次の子にも会いに来てね。チャンネル登録で、新しい動画をお知らせします。")


def cmd_promote(min_views: int, limit: int, apply: bool) -> None:
    yt = _yt()
    pl = None
    req = yt.playlists().list(part="snippet", mine=True, maxResults=50)
    while req and not pl:
        res = req.execute()
        pl = next((p for p in res["items"] if p["snippet"]["title"] == "猫と旅の一言シリーズ"), None)
        req = yt.playlists().list_next(req, res)
    if not pl:
        sys.exit("再生リスト「猫と旅の一言シリーズ」がありません（先に sync-playlists --apply）")
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = []
    req = yt.playlistItems().list(part="contentDetails", playlistId=up, maxResults=50)
    while req:
        res = req.execute()
        ids += [i["contentDetails"]["videoId"] for i in res["items"]]
        req = yt.playlistItems().list_next(req, res)
    hits = []
    for k in range(0, len(ids), 50):
        for v in yt.videos().list(part="snippet,statistics,status,liveStreamingDetails",
                                  id=",".join(ids[k:k + 50])).execute()["items"]:
            sn = v["snippet"]
            if (v["status"]["privacyStatus"] == "public" and int(v["statistics"].get("viewCount", 0)) >= min_views
                    and kind(sn["title"], "liveStreamingDetails" in v) == "猫と旅の一言シリーズ"
                    and PROMO_MARK not in sn.get("description", "")):
                hits.append((int(v["statistics"]["viewCount"]), v["id"], sn))
    hits.sort(key=lambda h: -h[0])
    text = promo_text(pl["id"])
    for views, vid, sn in hits[:limit]:
        print(f"{vid}（再生 {views}）: {sn['title']}")
        if apply:
            body = {k: sn[k] for k in ("title", "description", "tags", "categoryId",
                                       "defaultLanguage", "defaultAudioLanguage") if k in sn}
            body["description"] = text + ("\n\n" + sn["description"] if sn.get("description") else "")
            yt.videos().update(part="snippet", body={"id": vid, "snippet": body}).execute()
    print(("足しました" if apply else "試しのみ（--apply で実際に足す）") + f": {min(len(hits), limit)} 本（対象 {len(hits)} 本）")


def cmd_playlist(title: str, desc: str, ids: list[str], apply: bool, limit: int = 10 ** 6) -> int:
    """足した本数（試しのときは足す予定の本数）を返す。"""
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
            print(f"試しのみ: {min(len(ids), limit)} 本を足す予定")
            return min(len(ids), limit)
        pl = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": title, "description": desc},
            "status": {"privacyStatus": "public"}}).execute()
        pl["_new"] = True
    have = set()
    # 作ったばかりの再生リストは、しばらく中身の一覧を引けない（空なので引かなくてよい）
    req = None if pl.get("_new") else yt.playlistItems().list(part="contentDetails", playlistId=pl["id"], maxResults=50)
    while req:
        res = req.execute()
        have |= {i["contentDetails"]["videoId"] for i in res["items"]}
        req = yt.playlistItems().list_next(req, res)
    add = [i for i in ids if i not in have][:max(0, limit)]
    print(f"{title}: {len(have)} 本入り、{len(add)} 本を足す（残り {len([i for i in ids if i not in have]) - len(add)} 本）")
    if apply:
        import time
        from googleapiclient.errors import HttpError
        for vid in add:
            # 続けて足すと「409 SERVICE_UNAVAILABLE」が返ることがある。間を空けてやり直す
            for wait in (1, 4, 10, 30, None):
                try:
                    yt.playlistItems().insert(part="snippet", body={"snippet": {
                        "playlistId": pl["id"], "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
                    break
                except HttpError as e:
                    if wait is None or e.resp.status not in (409, 500, 503):
                        raise
                    time.sleep(wait)
            time.sleep(0.5)
        print(f"https://www.youtube.com/playlist?list={pl['id']}")
    return len(add)


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
    pr = sub.add_parser("promote")
    pr.add_argument("--min", type=int, default=1000)
    pr.add_argument("--limit", type=int, default=30)
    pr.add_argument("--apply", action="store_true")
    sy = sub.add_parser("sync-playlists")
    sy.add_argument("--limit", type=int, default=40)
    sy.add_argument("--apply", action="store_true")
    a = p.parse_args()
    if a.cmd == "titles":
        cmd_titles(a.csv, a.limit, a.apply)
    elif a.cmd == "promote":
        cmd_promote(a.min, a.limit, a.apply)
    elif a.cmd == "sync-playlists":
        cmd_sync(a.limit, a.apply)
    else:
        cmd_playlist(a.title, a.desc, [i for i in a.ids.split(",") if i], a.apply)


if __name__ == "__main__":
    main()

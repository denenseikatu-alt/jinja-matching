#!/usr/bin/env python3
"""英語圏向けの日本観光動画を1本、YouTube に上げる（2026-11 オーナー依頼）。

    python3 upload_tourism.py --video ep1v2_final.mp4 --thumb ep1_thumb.jpg \
        --srt ep1v2.srt --meta ep1v2_upload.txt                    # 読み取った内容を表示するだけ
    python3 upload_tourism.py ... --apply                           # 今すぐ公開
    python3 upload_tourism.py ... --publish-at 2026-11-09T18:00 --apply   # 日本時間で予約公開

- 題名・説明文・タグは *_upload.txt のとおり（説明文は書き換えない）。
- サムネイルと英語字幕（SRT）を設定し、合成コンテンツ（AI 音声）の申告をオンにする。
- 認証は yt_manage.py と同じ（~/.video_env の YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN）。

*_upload.txt の書き方（見出しは英語・日本語どちらでもよい。見出しの行に続けて書いても、次の行から書いてもよい）:
    Title: ...
    Description:
    ...（複数行。Tags の見出しの前まで）
    Tags: tag1, tag2, ...
読み取れない形なら止まる（推測で埋めない）。
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))


def parse_meta(text: str) -> dict:
    """見出し（Title / Description / Tags、または日本語）の行で区切って読む。"""
    pat = re.compile(r"^\s*[#\[【]*\s*(?:(?P<title>title|タイトル|題名)|(?P<description>description|説明文|説明|概要欄)"
                     r"|(?P<tags>tags|タグ))\s*[\]】]*\s*(?:[:：]\s*(?P<rest>.*)|$)", re.IGNORECASE)
    sections: dict[str, list[str]] = {}
    cur = None
    for ln in text.replace("\r\n", "\n").split("\n"):
        m = pat.match(ln)
        if m:
            cur = next(k for k in ("title", "description", "tags") if m.group(k))
            if cur in sections:
                sys.exit(f"見出し「{cur}」が2回あります。*_upload.txt を確かめてください")
            sections[cur] = [m.group("rest")] if m.group("rest") else []
            continue
        if cur:
            sections[cur].append(ln)
    for k in ("title", "description", "tags"):
        if k not in sections:
            sys.exit(f"*_upload.txt に「{k}」の見出しが見つかりません（Title: / Description: / Tags: の形にしてください）")
    title = "\n".join(sections["title"]).strip()
    desc = "\n".join(sections["description"]).strip("\n")
    tags_raw = " ".join(x.strip() for x in sections["tags"] if x.strip())
    tags = [t.strip().lstrip("#") for t in re.split(r"[,、，]", tags_raw) if t.strip()]
    if not title or "\n" in title:
        sys.exit(f"題名が1行になっていません: {title!r}")
    if len(title) > 100:
        sys.exit(f"題名が100文字を超えています（{len(title)}文字）")
    if len(desc.encode("utf-8")) > 5000:
        sys.exit("説明文が5000バイトを超えています")
    if sum(len(t) + 2 for t in tags) > 500:
        sys.exit("タグの合計が500文字を超えています")
    return {"title": title, "description": desc, "tags": tags}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--thumb", required=True)
    ap.add_argument("--srt", required=True)
    ap.add_argument("--meta", required=True, help="*_upload.txt")
    ap.add_argument("--publish-at", help="予約公開の日時（日本時間）例: 2026-11-09T18:00。無ければ今すぐ公開")
    ap.add_argument("--category", default="19", help="カテゴリ（既定 19: 旅行とイベント）")
    ap.add_argument("--apply", action="store_true", help="実際にアップロードする（無ければ表示だけ）")
    a = ap.parse_args()

    for p in (a.video, a.thumb, a.srt, a.meta):
        if not Path(p).is_file():
            sys.exit(f"ファイルがありません: {p}")
    meta = parse_meta(Path(a.meta).read_text(encoding="utf-8"))
    status = {"containsSyntheticMedia": True, "selfDeclaredMadeForKids": False}
    if a.publish_at:
        when = datetime.fromisoformat(a.publish_at)
        when = when.replace(tzinfo=JST) if when.tzinfo is None else when
        if when <= datetime.now(JST) + timedelta(minutes=15):
            sys.exit("予約の日時は15分以上先にしてください")
        status.update(privacyStatus="private", publishAt=when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    else:
        status["privacyStatus"] = "public"

    print(f"動画: {a.video}（{Path(a.video).stat().st_size / 1e6:.0f}MB）")
    print(f"題名: {meta['title']}")
    print(f"タグ（{len(meta['tags'])}個）: {', '.join(meta['tags'])}")
    print(f"説明文（{len(meta['description'])}文字）:\n----\n{meta['description']}\n----")
    print(f"サムネイル: {a.thumb} / 字幕（英語）: {a.srt}")
    print("公開: " + (f"予約 {a.publish_at}（日本時間）" if a.publish_at else "今すぐ公開") + " / 合成コンテンツの申告: オン")
    if not a.apply:
        print("表示だけです。内容が正しければ --apply を付けて実行してください")
        return

    from googleapiclient.http import MediaFileUpload
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from yt_manage import _yt
    yt = _yt()
    body = {"snippet": {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
                        "categoryId": a.category, "defaultLanguage": "en", "defaultAudioLanguage": "en"},
            "status": status}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(a.video, chunksize=16 * 1024 * 1024, resumable=True))
    res = None
    while res is None:
        st, res = req.next_chunk()
        if st:
            print(f"送信中 {int(st.progress() * 100)}%", flush=True)
    vid = res["id"]
    print(f"アップロード完了: https://www.youtube.com/watch?v={vid}", flush=True)
    yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(a.thumb)).execute()
    print("サムネイルを設定しました", flush=True)
    yt.captions().insert(part="snippet", body={"snippet": {"videoId": vid, "language": "en", "name": "English",
                                                           "isDraft": False}},
                         media_body=MediaFileUpload(a.srt, mimetype="application/octet-stream")).execute()
    print("英語字幕を設定しました", flush=True)
    v = yt.videos().list(part="snippet,status", id=vid).execute()["items"][0]
    s = v["status"]
    print(f"確認: {vid} 公開設定={s['privacyStatus']} 予約={s.get('publishAt', 'なし')} "
          f"合成コンテンツ={s.get('containsSyntheticMedia')} 題名={v['snippet']['title']}")
    print(f"URL: https://www.youtube.com/watch?v={vid}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""週1回のふりかえり動画（10分以上）の材料を集めて review_source.json に書く。

- 直近7日（日本時間）に投稿した雑学動画: 共有台帳（zatsugaku-state）の題名・テーマ・10個の雑学と出典
  （台帳に雑学がない古い回は、リポジトリの zatsugaku/scripts/<記録先>.json から読む）
- 同じ期間に投稿した記事動画: YouTube の題名と概要欄
- それぞれの再生回数（よく見られた回を厚めに扱うため）

今週のふりかえりをすでに投稿していれば、終了コード 3 で終わる（題名の「MARK」で見分ける）。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "zatsugaku"))

from yt_auth import _env_credentials  # noqa: E402
import zatsugaku_state  # noqa: E402

JST = timezone(timedelta(hours=9))
MARK = "今週の体づくり雑学ふりかえり"
DAYS = 7


def video_id(url: str) -> str | None:
    m = re.search(r"(?:youtu\.be/|v=|shorts/)([\w-]{11})", url or "")
    return m.group(1) if m else None


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "review_source.json")
    now = datetime.now(JST)
    since = (now - timedelta(days=DAYS)).date().isoformat()
    from googleapiclient.discovery import build

    yt = build("youtube", "v3", credentials=_env_credentials(), cache_discovery=False)
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    recent = []
    req = yt.playlistItems().list(part="snippet,contentDetails", playlistId=uploads, maxResults=50)
    res = req.execute()
    for it in res["items"]:
        pub = datetime.fromisoformat(it["contentDetails"]["videoPublishedAt"].replace("Z", "+00:00"))
        if pub.astimezone(JST).date().isoformat() >= since:
            recent.append({"id": it["contentDetails"]["videoId"], "title": it["snippet"]["title"],
                           "desc": it["snippet"]["description"][:600],
                           "published": pub.astimezone(JST).strftime("%Y-%m-%d %H:%M")})
    if any(MARK in v["title"] for v in recent if v["published"][:10] > (now - timedelta(days=6)).date().isoformat()):
        print("今週のふりかえり動画は投稿済みです")
        sys.exit(3)
    views = {}
    ids = [v["id"] for v in recent]
    for k in range(0, len(ids), 50):
        for v in yt.videos().list(part="statistics", id=",".join(ids[k:k + 50])).execute()["items"]:
            views[v["id"]] = int(v["statistics"].get("viewCount", 0))

    st = zatsugaku_state.read_shared()
    zatsu = []
    for key, d in sorted(st.get("done", {}).items()):
        if not re.match(r"\d{4}-\d{2}-\d{2}", key) or key[:10] < since or not d.get("url"):
            continue
        items = d.get("items")
        if not items:
            f = ROOT / "zatsugaku" / "scripts" / f"{key}.json"
            if f.exists():
                sc = json.loads(f.read_text(encoding="utf-8"))
                items = [{"topic": it.get("topic"), "source": it.get("source"), "pmid": it.get("pmid"),
                          "url": it.get("url"),
                          "say": "".join(ln.get("say", "") for ln in it.get("lines", []))}
                         for it in sc.get("items", [])[1:-1]]
        vid = video_id(d["url"])
        zatsu.append({"key": key, "theme": d.get("theme"), "title": d.get("title"), "url": d["url"],
                      "views": views.get(vid), "items": items or []})
    articles = [{**v, "url": f"https://youtu.be/{v['id']}", "views": views.get(v["id"])}
                for v in recent if "｜" in v["title"] and not v["title"].startswith("9割")
                and MARK not in v["title"]]
    data = {"made": now.strftime("%Y-%m-%d"), "since": since, "mark": MARK,
            "zatsugaku": zatsu, "articles": articles}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    n_items = sum(len(z["items"]) for z in zatsu)
    print(f"材料: 雑学動画 {len(zatsu)}本（雑学 {n_items}個）・記事動画 {len(articles)}本 → {out}")


if __name__ == "__main__":
    main()

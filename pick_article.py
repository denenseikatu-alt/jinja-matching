#!/usr/bin/env python3
"""毎日1本ずつ動画にするために、まだ処理していない記事を1つ選ぶ。

    # 次の記事を1つ選ぶ（選ぶだけ。記録はしない）
    python3 pick_article.py --site ~/Downloads/denenseikatu-site

    # アップロードまで終わったら記録する
    python3 pick_article.py --done <スラッグ> --url <動画URL>

    # 進捗を見る
    python3 pick_article.py --status

    # クラウド: 記事一覧はサイトの sitemap から、処理済みは YouTube の投稿から判断する
    python3 pick_article.py --sitemap https://denenseikatu.com/sitemap.xml --youtube

処理済みの記録は video_state.json に残る。同じ記事を二度上げないための台帳。
--youtube を付けると、台帳の代わりにチャンネルの投稿済み動画の概要欄にある記事URLを
処理済みとみなす（Mac とクラウドのどちらで上げたものも拾える）。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_STATE = REPO_ROOT / "video_state.json"


def load_state(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"done": {}}


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def list_articles(site: Path) -> list[str]:
    articles = site / "articles"
    if not articles.is_dir():
        sys.exit(f"記事ディレクトリがありません: {articles}")
    slugs = [
        d.name for d in sorted(articles.iterdir())
        if d.is_dir() and (d / "index.html").is_file()
    ]
    if not slugs:
        sys.exit(f"記事が1件も見つかりません: {articles}")
    return slugs


ARTICLE_URL = re.compile(r"https://denenseikatu\.com/articles/([^/\s]+)/")


def list_articles_sitemap(url: str) -> list[str]:
    import urllib.request

    from extract_article import USER_AGENT

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml = resp.read().decode("utf-8", "replace")
    slugs = sorted({m.group(1) for loc in re.findall(r"<loc>([^<]+)</loc>", xml)
                    if (m := ARTICLE_URL.fullmatch(loc.strip()))})
    if not slugs:
        sys.exit(f"sitemap に記事が見つかりません: {url}")
    return slugs


def youtube_done() -> dict:
    """チャンネルの投稿済み動画から、動画にした記事を集める。{スラッグ: {date, url}}"""
    from googleapiclient.discovery import build

    from yt_auth import load_credentials

    yt = build("youtube", "v3", credentials=load_credentials())
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    if not ch.get("items"):
        sys.exit("YouTube チャンネルが見つかりません。")
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    done: dict = {}
    token = None
    while True:
        page = yt.playlistItems().list(part="snippet", playlistId=uploads,
                                       maxResults=50, pageToken=token).execute()
        for item in page.get("items", []):
            sn = item["snippet"]
            for slug in ARTICLE_URL.findall(sn.get("description", "")):
                vid = sn.get("resourceId", {}).get("videoId", "")
                done.setdefault(slug, {"date": sn.get("publishedAt", ""),
                                       "url": f"https://www.youtube.com/watch?v={vid}"})
        token = page.get("nextPageToken")
        if not token:
            return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default="~/Downloads/denenseikatu-site",
                    help="サイトのローカルコピー (既定: ~/Downloads/denenseikatu-site)")
    ap.add_argument("--state", default=str(DEFAULT_STATE), help="進捗の記録先")
    ap.add_argument("--random", action="store_true", help="順番ではなく無作為に選ぶ")
    ap.add_argument("--done", metavar="スラッグ", help="この記事を処理済みとして記録する")
    ap.add_argument("--url", help="--done と一緒に使う。アップロードした動画のURL")
    ap.add_argument("--status", action="store_true", help="進捗だけ表示して終わる")
    ap.add_argument("--sitemap", metavar="URL",
                    help="記事一覧をローカルコピーではなく sitemap.xml から取る")
    ap.add_argument("--youtube", action="store_true",
                    help="処理済みを台帳ではなく YouTube の投稿済み動画から判断する")
    ap.add_argument("--skip-if-within", type=float, metavar="時間", default=None,
                    help="--youtube と併用。直近この時間内に記事動画を上げていたら何もせず終了（終了コード 3）")
    args = ap.parse_args()

    site = Path(args.site).expanduser()
    state_path = Path(args.state).expanduser()
    state = load_state(state_path)
    done = state.setdefault("done", {})

    if args.done and args.youtube:
        sys.exit("--youtube のときは記録は不要です（投稿した動画そのものが記録になります）。")
    if args.done:
        done[args.done] = {"date": date.today().isoformat(), "url": args.url or ""}
        save_state(state_path, state)
        print(f"記録しました: {args.done}")
        return

    slugs = list_articles_sitemap(args.sitemap) if args.sitemap else list_articles(site)
    if args.youtube:
        done = youtube_done()
        if args.skip_if_within is not None and done:
            latest = max(datetime.fromisoformat(v["date"].replace("Z", "+00:00"))
                         for v in done.values() if v["date"])
            if datetime.now(timezone.utc) - latest < timedelta(hours=args.skip_if_within):
                print(f"直近 {args.skip_if_within:g} 時間以内に投稿済みです（{latest.isoformat()}）。今日はスキップします。")
                sys.exit(3)
    remaining = [s for s in slugs if s not in done]

    if args.status:
        print(f"全 {len(slugs)} 本 / 済 {len(done)} 本 / 残り {len(remaining)} 本")
        if remaining:
            print(f"次: {remaining[0]}")
        return

    if not remaining:
        print("すべての記事が処理済みです。")
        sys.exit(2)

    slug = random.choice(remaining) if args.random else remaining[0]
    url = f"https://denenseikatu.com/articles/{slug}/"
    path = url if args.sitemap else site / "articles" / slug / "index.html"

    print(f"スラッグ: {slug}")
    print(f"パス:     {path}")
    print(f"URL:      https://denenseikatu.com/articles/{slug}/")
    print(f"進捗:     済 {len(done)} / 全 {len(slugs)}（残り {len(remaining) - 1}）")


if __name__ == "__main__":
    main()

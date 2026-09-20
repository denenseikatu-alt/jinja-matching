#!/usr/bin/env python3
"""毎日1本ずつ動画にするために、まだ処理していない記事を1つ選ぶ。

    # 次の記事を1つ選ぶ（選ぶだけ。記録はしない）
    python3 pick_article.py --site ~/Downloads/denenseikatu-site

    # アップロードまで終わったら記録する
    python3 pick_article.py --done <スラッグ> --url <動画URL>

    # 進捗を見る
    python3 pick_article.py --status

処理済みの記録は video_state.json に残る。同じ記事を二度上げないための台帳。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default="~/Downloads/denenseikatu-site",
                    help="サイトのローカルコピー (既定: ~/Downloads/denenseikatu-site)")
    ap.add_argument("--state", default=str(DEFAULT_STATE), help="進捗の記録先")
    ap.add_argument("--random", action="store_true", help="順番ではなく無作為に選ぶ")
    ap.add_argument("--done", metavar="スラッグ", help="この記事を処理済みとして記録する")
    ap.add_argument("--url", help="--done と一緒に使う。アップロードした動画のURL")
    ap.add_argument("--status", action="store_true", help="進捗だけ表示して終わる")
    args = ap.parse_args()

    site = Path(args.site).expanduser()
    state_path = Path(args.state).expanduser()
    state = load_state(state_path)
    done = state.setdefault("done", {})

    if args.done:
        done[args.done] = {"date": date.today().isoformat(), "url": args.url or ""}
        save_state(state_path, state)
        print(f"記録しました: {args.done}")
        return

    slugs = list_articles(site)
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
    path = site / "articles" / slug / "index.html"

    print(f"スラッグ: {slug}")
    print(f"パス:     {path}")
    print(f"URL:      https://denenseikatu.com/articles/{slug}/")
    print(f"進捗:     済 {len(done)} / 全 {len(slugs)}（残り {len(remaining) - 1}）")


if __name__ == "__main__":
    main()

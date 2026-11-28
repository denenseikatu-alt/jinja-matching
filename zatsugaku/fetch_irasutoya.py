#!/usr/bin/env python3
"""台本の image_query をいらすとやで検索し、絵を assets/irasutoya/ に取ってきて image を埋める。

    python3 fetch_irasutoya.py scripts/2026-10-02.json

1枚の絵だけのページ（png）を優先し、複数の絵をまとめたサムネイル（jpg）は使わない。
見つからなければ image_query_alt、検索語を1語ずつ、テーマ名の順に探し直す。
それでも無ければ汎用の絵（hirameki_man.png）を使い、止まらずに進める。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG_DIR = HERE / "assets" / "irasutoya"
UA = {"User-Agent": "Mozilla/5.0"}
LIMIT = 20  # いらすとやの利用規約：1作品につき20点まで


def search(query: str) -> list[tuple[str, str, str]]:
    u = ("https://www.irasutoya.com/feeds/posts/summary?alt=json&max-results=10&q="
         + urllib.parse.quote(query))
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
    hits = []
    for e in d["feed"].get("entry", []):
        thumb = e.get("media$thumbnail", {}).get("url", "")
        page = next(l["href"] for l in e["link"] if l["rel"] == "alternate")
        m = re.search(r"/s72-c/([^/]+\.png)$", thumb)
        if m and not m.group(1).startswith("thumbnail_"):
            hits.append((e["title"]["$t"], page, thumb.replace("/s72-c/", "/s800/")))
    return hits


def download(url: str, name: str) -> Path:
    path = IMG_DIR / name
    if not path.exists():
        for size in ("/s800/", "/s400/"):
            try:
                data = urllib.request.urlopen(
                    urllib.request.Request(url.replace("/s800/", size), headers=UA), timeout=60).read()
                if data[:4] == b"\x89PNG":
                    path.write_bytes(data)
                    break
            except Exception:
                continue
        else:
            raise RuntimeError(f"取得できません: {url}")
    return path


def main() -> None:
    script_path = Path(sys.argv[1])
    sc = json.loads(script_path.read_text(encoding="utf-8"))
    used: set[str] = {it["image"] for it in sc["items"] if it.get("image")}

    for it in sc["items"]:
        if it.get("image"):
            continue
        hit = None
        queries = [it.get("image_query"), it.get("image_query_alt")]
        for q in list(queries):
            if q and " " in q.strip():
                queries += q.split()
        queries.append(sc.get("theme"))
        for q in dict.fromkeys(q for q in queries if q):
            if not q:
                continue
            for title, page, url in search(q):
                name = url.rsplit("/", 1)[1]
                if name not in used:  # 1本の中で同じ絵を使い回さない
                    hit = (title, page, url, name)
                    break
            if hit:
                break
        if not hit:
            print(f"  注意: いらすとやで絵が見つからないため汎用の絵を使います: {it.get('image_query')}")
            it["image"] = "hirameki_man.png"
            continue
        title, page, url, name = hit
        download(url, name)
        it["image"] = name
        it["image_page"] = page
        used.add(name)
        print(f"  {it.get('image_query')} → {title}（{name}）")

    if len(used) > LIMIT:
        sys.exit(f"いらすとやは1作品{LIMIT}点までです（{len(used)}点）")
    script_path.write_text(json.dumps(sc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"絵 {len(used)}点")


if __name__ == "__main__":
    main()

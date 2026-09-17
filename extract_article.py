#!/usr/bin/env python3
"""denenseikatu.com のコラム記事から、動画台本のもとになる本文を抽出する。

使い方:
    python3 extract_article.py https://denenseikatu.com/column/sanpai-saho/
    python3 extract_article.py column/sanpai-saho/index.html -o article.json

URL を渡した場合、まずローカルのリポジトリ内に対応する HTML があればそれを読む
(サイトと同じ内容が手元にあるため、ネットワークに出ずに済む)。
無ければ HTTP で取得する。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent

# ブロックごと捨てる定型（パンくず・免責）
SKIP_PATTERNS = (
    "ホーム ›",
    "本記事は神社・神道に関する一般的な読み物",
    "本記事の一部は生成AIを活用",
)
# 文単位で捨てる定型（本文末尾に付く導線）
SKIP_SENTENCES = ("無料で診断", "診断してみません")
# この見出し以降は本文ではない
STOP_HEADINGS = ("関連コラム", "関連記事")


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"\s+", " ", text).strip()


def drop_cta_sentences(text: str) -> str:
    """本文末尾に付く診断への導線だけを、文単位で取り除く。"""
    parts = re.findall(r"[^。！？]*[。！？]|[^。！？]+$", text)
    kept = [p for p in parts if not any(s in p for s in SKIP_SENTENCES)]
    return "".join(kept).strip()


def load_html(target: str) -> tuple[str, str]:
    """(html, source_url) を返す。"""
    if target.startswith(("http://", "https://")):
        parsed = urlparse(target)
        rel = parsed.path.strip("/")
        candidates = []
        if rel:
            candidates += [REPO_ROOT / rel, REPO_ROOT / rel / "index.html"]
        else:
            candidates.append(REPO_ROOT / "index.html")
        for cand in candidates:
            if cand.is_file():
                return cand.read_text(encoding="utf-8"), target
        # ローカルに無ければ取得
        import urllib.request

        with urllib.request.urlopen(target, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace"), target

    path = Path(target)
    if not path.is_file() and (path / "index.html").is_file():
        path = path / "index.html"
    if not path.is_file():
        sys.exit(f"記事が見つかりません: {target}")
    rel = path.resolve().relative_to(REPO_ROOT).parent.as_posix()
    return path.read_text(encoding="utf-8"), f"https://denenseikatu.com/{rel}/"


def extract(html: str, source_url: str) -> dict:
    body = re.search(r"<main[^>]*>(.*?)</main>", html, re.S) or re.search(
        r"<article[^>]*>(.*?)</article>", html, re.S
    )
    segment = body.group(1) if body else html
    segment = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", segment, flags=re.S)

    title = ""
    sections: list[dict] = []
    current: dict | None = None

    for tag, inner in re.findall(r"<(h1|h2|h3|p|li)[^>]*>(.*?)</\1>", segment, re.S):
        text = strip_tags(inner)
        if not text or any(p in text for p in SKIP_PATTERNS):
            continue
        text = drop_cta_sentences(text)
        if not text:
            continue

        if tag == "h1":
            title = text
            continue
        if tag == "h2":
            if any(text.startswith(s) for s in STOP_HEADINGS):
                break
            current = {"heading": text, "blocks": []}
            sections.append(current)
            continue

        if current is None:
            # h2 より前の導入文
            current = {"heading": "", "blocks": []}
            sections.append(current)
        kind = "sub" if tag == "h3" else ("bullet" if tag == "li" else "text")
        current["blocks"].append({"kind": kind, "text": text})

    sections = [s for s in sections if s["blocks"] or s["heading"]]
    if not title:
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = strip_tags(m.group(1)) if m else "無題"

    return {"title": title, "source_url": source_url, "sections": sections}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="記事の URL またはローカルパス")
    ap.add_argument("-o", "--output", default="article.json", help="出力 JSON (既定: article.json)")
    args = ap.parse_args()

    html, source_url = load_html(args.target)
    article = extract(html, source_url)
    Path(args.output).write_text(
        json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    blocks = sum(len(s["blocks"]) for s in article["sections"])
    print(f"タイトル: {article['title']}")
    print(f"セクション {len(article['sections'])} / ブロック {blocks} → {args.output}")


if __name__ == "__main__":
    main()

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

# 本文ではない領域。構造で落とすので、サイトが変わってもそのまま効く。
STRIP_ELEMENTS = ("script", "style", "nav", "header", "footer", "aside", "form", "noscript")

# ブロックごと捨てる定型（サイト固有。--skip で足せる）
SKIP_PATTERNS = (
    "本記事は神社・神道に関する一般的な読み物",
    "本記事の一部は生成AIを活用",
)
# 文単位で捨てる定型（本文末尾に付く導線。--skip-sentence で足せる）
SKIP_SENTENCES = ("無料で診断", "診断してみません")
# この見出し以降は本文ではない（h2 でも h3 でも打ち切る）
STOP_HEADINGS = (
    "関連コラム",
    "関連記事",
    "あわせて読みたい",
    "こちらもおすすめ",
    "よくある質問",
    "読んだら",
    "次の一歩",
)

# パンくずの区切り文字。2個以上並んでいたらパンくずとみなす。
BREADCRUMB_SEPARATORS = ("›", "»", "＞", ">", "▸", "/")


def looks_like_breadcrumb(text: str) -> bool:
    """「ホーム › コラム › 記事名」のような行を、文字列決め打ちではなく形で判定する。"""
    if len(text) > 200:
        return False
    for sep in BREADCRUMB_SEPARATORS:
        if text.count(sep) >= 2:
            return True
        # 「ホーム › 記事名」のように区切りが1つだけのパンくずも拾う
        if text.count(sep) == 1 and re.match(r"^\s*(ホーム|トップ|HOME|Home|TOP)\s*" + re.escape(sep), text):
            return True
    return False


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
    return path.read_text(encoding="utf-8"), ""


def canonical_url(html: str) -> str:
    """記事が自称する正規URL。ドメインを決め打ちせず、必ずHTMLから取る。"""
    for pattern in (
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
        r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)',
    ):
        m = re.search(pattern, html, re.I)
        if m:
            return m.group(1)
    return ""


def site_name(html: str) -> str:
    m = re.search(
        r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', html, re.I
    )
    return m.group(1) if m else ""


def extract(html: str, source_url: str) -> dict:
    body = re.search(r"<main[^>]*>(.*?)</main>", html, re.S) or re.search(
        r"<article[^>]*>(.*?)</article>", html, re.S
    )
    segment = body.group(1) if body else html
    for tag in STRIP_ELEMENTS:
        segment = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", segment, flags=re.S | re.I)

    title = ""
    sections: list[dict] = []
    current: dict | None = None

    for tag, inner in re.findall(r"<(h1|h2|h3|p|li)[^>]*>(.*?)</\1>", segment, re.S):
        text = strip_tags(inner)
        if not text or any(p in text for p in SKIP_PATTERNS):
            continue
        if tag in ("p", "li") and looks_like_breadcrumb(text):
            continue
        text = drop_cta_sentences(text)
        if not text:
            continue

        if tag == "h1":
            title = text
            continue
        # 打ち切り見出しは h2 とは限らない。h3 で「関連記事」が来るサイトもある。
        if tag in ("h2", "h3") and any(s in text for s in STOP_HEADINGS):
            break
        if tag == "h2":
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

    # canonical を最優先する。渡されたURLがリダイレクト前だったり、
    # ローカルパスでドメインが分からない場合があるため。
    canonical = canonical_url(html)
    if canonical:
        source_url = canonical
    if not source_url:
        sys.exit(
            "記事の正規URLが判定できません。\n"
            "HTML に canonical も og:url も無く、ローカルパスから渡されました。\n"
            "URL を直接指定して実行してください。"
        )

    host = urlparse(source_url).netloc
    return {
        "title": title,
        "source_url": source_url,
        "site": site_name(html) or host,
        "site_host": host,
        "sections": sections,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="記事の URL またはローカルパス")
    ap.add_argument("-o", "--output", default="article.json", help="出力 JSON (既定: article.json)")
    ap.add_argument("--skip", action="append", default=[], metavar="文字列",
                    help="この文字列を含むブロックを捨てる（複数指定可）")
    ap.add_argument("--skip-sentence", action="append", default=[], metavar="文字列",
                    help="この文字列を含む「文」だけを捨てる（複数指定可）")
    ap.add_argument("--dump", action="store_true", help="抽出結果を標準出力にも表示する")
    args = ap.parse_args()

    global SKIP_PATTERNS, SKIP_SENTENCES
    SKIP_PATTERNS = tuple(SKIP_PATTERNS) + tuple(args.skip)
    SKIP_SENTENCES = tuple(SKIP_SENTENCES) + tuple(args.skip_sentence)

    html, source_url = load_html(args.target)
    article = extract(html, source_url)
    Path(args.output).write_text(
        json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    blocks = sum(len(s["blocks"]) for s in article["sections"])
    print(f"タイトル: {article['title']}")
    print(f"サイト: {article['site']} ({article['site_host']})")
    print(f"セクション {len(article['sections'])} / ブロック {blocks} → {args.output}")

    if args.dump:
        print()
        for s in article["sections"]:
            print("##", s["heading"] or "(導入)")
            for b in s["blocks"]:
                print(f"   [{b['kind']}] {b['text']}")

    print("\n本文でないものが混ざっていたら --skip / --skip-sentence で除いてください。")


if __name__ == "__main__":
    main()

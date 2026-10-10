#!/usr/bin/env python3
"""雑学動画の台本検査と台帳（重複防止・二重投稿防止）。

台帳 state.json は GitHub の zatsugaku-state ブランチに置き、Mac とクラウドで共有する。
書き込みは「取得→書き換え→push」を push が通るまで繰り返す（同時に書いても片方が負けて読み直す）。

    python3 zatsugaku_state.py pull                      # 台帳を手元の state.json に取ってくる
    python3 zatsugaku_state.py claim --by mac            # 今日の担当を取る（終了コード 3 = 今日は不要）
    python3 zatsugaku_state.py theme                     # 今日のテーマを表示する
    python3 zatsugaku_state.py skip-theme                # 今日のテーマでネタがそろわないとき、次のテーマに切り替える
    python3 zatsugaku_state.py release --by mac          # 失敗したとき担当を手放す（もう一方が作れるように）
    python3 zatsugaku_state.py check scripts/<日付>.json
    python3 zatsugaku_state.py done  scripts/<日付>.json --url https://youtu.be/...
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
BRANCH = "zatsugaku-state"
JST = timezone(timedelta(hours=9))
CLAIM_HOURS = 3  # 担当を取ってからこの時間を過ぎたら、作成に失敗したとみなしてもう一方が作ってよい

BANNED = re.compile(r"[A-Z]{2,}")  # 英語の略語（RCT・LDL など）。kg・mg は小文字なので通る
ALLOWED_CAPS = ["NISA", "SNS", "AI"]  # 制度の正式名称と、日本語として定着した語だけ許す
BANNED_WORDS = ["メタ解析", "コホート", "エビデンス", "バイアス", "治る", "効く", "若返る",
                "必ず儲", "必ず増え", "損しない", "買うべき", "おすすめの銘柄",
                "ファイナンシャルプランナー", "マネーセミナー"]
# 1本の動画は1テーマ。毎日この順に1つずつ進む（健康と暮らし・人間関係がなるべく交互になる並び。28日で一巡）
# キーは画面と題名に出す短い呼び名（導入の画面に「〇〇の雑学」と入るので短くする）。値はテーマの範囲の説明で、
# 台本を書く Claude に渡す（オーナーの指示の言葉そのまま）。
THEME_SCOPE = {
    "筋トレ": "筋トレ",
    "恋愛": "恋愛",
    "栄養": "栄養",
    "婚活": "婚活",
    "プロテイン": "プロテイン",
    "幸福感": "幸福感",
    "ビタミン": "ビタミン",
    "夫婦生活": "夫婦生活のメリット・デメリット",
    "ダイエット": "ダイエット",
    "暮らし": "暮らし",
    "がんと生活習慣": "ガンになりやすい、なりにくい生活習慣",
    "女性が好む男性": "世代別女性が好む男性の特徴",
    "アンチエイジング": "アンチエイジング",
    "人生": "人生",
    "筋肥大": "筋肥大",
    "推し活": "推し活をする男女の特徴、心理、精神",
    "美容": "美容",
    "投資": "投資",
    "病気予防": "病気予防",
    "ネットで攻撃する人": "ネット上で他者を攻撃する人の特徴、心理、精神",
    "認知症予防": "認知症予防",
    "資産管理": "資産管理",
    "健康情報": "健康情報",
    "男性が好む女性": "世代別男性が好む女性の特徴",
    "結婚しない人生": "結婚しないメリット・デメリット",
    "睡眠": "睡眠（睡眠時間の重要性、健康に及ぼす影響、話題の自称ショートスリーパーの実際）",
    "顔出し発信する専門家": "YouTubeで顔出し情報発信する専門家の心理、心情、意味",
    "世代別の男女": "世代別男女の思考傾向や特徴",
}
THEMES = list(THEME_SCOPE)
MONEY = {"投資", "資産管理"}


def today() -> str:
    return datetime.now(JST).date().isoformat()


def theme_for(st: dict, day: str) -> str:
    """その日のテーマ。前日までに投稿した最後のテーマの次（固定した日はそのテーマ）。
    台帳だけで決まるので Mac とクラウドで一致する。固定した日のあとは、最後に投稿したテーマの次から続く。"""
    if day in st.get("done", {}) and st["done"][day].get("theme"):
        return st["done"][day]["theme"]
    # その日に「別のネタが10個そろわない」として外したテーマ（台帳の theme_skips）
    skips = set(st.get("theme_skips", {}).get(day, []))
    # オーナーの指示で日付ごとにテーマを固定した日（台帳の theme_overrides）。順番より優先する
    fixed = st.get("theme_overrides", {}).get(day)
    if fixed in THEMES and fixed not in skips:
        return fixed
    # 順番の位置は、順番どおりに選んだ回（固定した日を除く）の最後のテーマで決まる。
    # 追加で作った回（キーが「日付-extraN」）も順番を進める
    past = sorted((d, v["theme"]) for d, v in st.get("done", {}).items()
                  if d < day and v.get("theme") in THEMES and not v.get("fixed"))
    i = (THEMES.index(past[-1][1]) + 1) % len(THEMES) if past else 0
    for k in range(len(THEMES)):
        t = THEMES[(i + k) % len(THEMES)]
        if t not in skips:
            return t
    sys.exit("その日に使えるテーマが残っていません")


def next_theme(st: dict, skips: set[str] = frozenset()) -> str:
    """毎日の2本目（追加の回）のテーマ。これまでに順番どおり投稿した最後のテーマの次。
    追加の回もテーマの順番を進めるので、翌日の1本目はこの次のテーマになる。"""
    past = sorted((d, v["theme"]) for d, v in st.get("done", {}).items()
                  if v.get("theme") in THEMES and not v.get("fixed"))
    i = (THEMES.index(past[-1][1]) + 1) % len(THEMES) if past else 0
    for k in range(len(THEMES)):
        t = THEMES[(i + k) % len(THEMES)]
        if t not in skips:
            return t
    sys.exit("使えるテーマが残っていません")


def next_extra_key(st: dict, day: str) -> str:
    n = 1
    while f"{day}-extra{n}" in st.get("done", {}):
        n += 1
    return f"{day}-extra{n}"


def empty_state() -> dict:
    return {"used_topics": [], "used_sources": [], "done": {}, "claims": {}}


# --- 共有台帳（git ブランチ） ----------------------------------------------

def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _origin() -> str:
    r = _git("remote", "get-url", "origin", cwd=HERE)
    if r.returncode:
        sys.exit("git の origin が分かりません")
    return r.stdout.strip()


def _checkout(tmp: Path) -> Path:
    r = _git("clone", "-q", "--depth", "1", "-b", BRANCH, _origin(), str(tmp / "s"), cwd=tmp)
    repo = tmp / "s"
    if r.returncode:  # ブランチがまだ無い
        repo.mkdir()
        _git("init", "-q", cwd=repo)
        _git("checkout", "-q", "-b", BRANCH, cwd=repo)
        _git("remote", "add", "origin", _origin(), cwd=repo)
    return repo


def read_shared() -> dict:
    with tempfile.TemporaryDirectory() as t:
        f = _checkout(Path(t)) / "state.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    # 初回だけ、手元の台帳を種にする
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else empty_state()


def update_shared(change, message: str) -> dict:
    """change(state) を当てて push する。push が拒否されたら読み直してやり直す。"""
    for _ in range(5):
        with tempfile.TemporaryDirectory() as t:
            repo = _checkout(Path(t))
            f = repo / "state.json"
            if f.exists():
                st = json.loads(f.read_text(encoding="utf-8"))
            else:
                st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else empty_state()
            st.setdefault("claims", {})
            result = change(st)
            f.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _git("add", "state.json", cwd=repo)
            _git("-c", "user.name=denen-zatsugaku", "-c", "user.email=noreply@anthropic.com",
                 "commit", "-q", "-m", message, cwd=repo)
            if _git("push", "-q", "origin", BRANCH, cwd=repo).returncode == 0:
                STATE.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
                return result if result is not None else st
    sys.exit("台帳を書き込めませんでした（push が通りません）")


# --- コマンド -------------------------------------------------------------

def cmd_pull() -> None:
    st = read_shared()
    st.setdefault("claims", {})
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"台帳を取得しました（使用済みの話題 {len(st['used_topics'])}件・投稿 {len(st['done'])}本）")


def cmd_claim(by: str) -> None:
    day = today()

    def change(st):
        if day in st["done"]:
            return f"DONE {st['done'][day].get('url', '')}"
        c = st["claims"].get(day)
        if c and c["by"] != by:
            age = datetime.now(JST) - datetime.fromisoformat(c["at"])
            if age < timedelta(hours=CLAIM_HOURS):
                return f"BUSY {c['by']}（{int(age.total_seconds() // 60)}分前から作成中）"
        st["claims"][day] = {"by": by, "at": datetime.now(JST).isoformat(timespec="seconds"),
                             "theme": theme_for(st, day)}
        return "OK " + st["claims"][day]["theme"]

    r = update_shared(change, f"{day} の担当: {by}")
    if r.startswith("DONE"):
        print(f"今日（{day}）の雑学動画は投稿済みです: {r[5:]}")
        sys.exit(3)
    if r.startswith("BUSY"):
        print(f"今日（{day}）の雑学動画は {r[5:]}。こちらでは作りません")
        sys.exit(3)
    print(f"今日（{day}）の担当を取りました: {by}")
    print(f"THEME: {r[3:]}")


def cmd_release(by: str) -> None:
    day = today()

    def change(st):
        if st["claims"].get(day, {}).get("by") == by:
            del st["claims"][day]
    update_shared(change, f"{day} の担当を手放す: {by}")
    print(f"今日の担当を手放しました: {by}")


def cmd_skip_theme() -> None:
    """今日のテーマでは確かめられた別のネタが10個そろわないとき、順番で次のテーマに切り替える。"""
    day = today()

    def change(st):
        cur = theme_for(st, day)
        st.setdefault("theme_skips", {}).setdefault(day, []).append(cur)
        new = theme_for(st, day)
        if day in st["claims"]:
            st["claims"][day]["theme"] = new
        return f"{cur}→{new}"
    r = update_shared(change, f"{day} のテーマを切り替え（ネタが10個そろわない）")
    cur, new = r.split("→")
    print(f"「{cur}」は別のネタが10個そろわないため、今日のテーマを「{new}」に切り替えました")
    print(f"THEME: {new}")
    print(f"範囲: {THEME_SCOPE[new]}")


def check(path: Path, theme: str | None = None) -> None:
    sc = json.loads(path.read_text(encoding="utf-8"))
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else empty_state()
    errs = []
    theme = theme or theme_for(st, today())
    if sc.get("theme") != theme:
        errs.append(f"theme が今日のテーマと違います（今日は「{theme}」）: {sc.get('theme')}")
    items = sc.get("items", [])
    body = items[1:-1]
    if len(body) != 10:
        errs.append(f"雑学が{len(body)}個です（10個にする）")
    total = 0
    for it in items:
        for ln in it.get("lines", []):
            cap, say = ln.get("caption", ""), ln.get("say", "")
            total += len(say)
            rows = cap.split("\n")
            if len(rows) > 2 or any(len(r) > 16 for r in rows):
                errs.append(f"画面の文字が長すぎます: {cap!r}")
            if len(say) > 70:
                errs.append(f"読み上げの1文が長すぎます（{len(say)}字）: {say[:20]}…")
            for t in (cap, say):
                if BANNED.search(re.sub("|".join(ALLOWED_CAPS), "", t)):
                    errs.append(f"英語の略語があります: {t!r}")
                for w in BANNED_WORDS:
                    if w in t:
                        errs.append(f"使わない言葉「{w}」があります: {t!r}")
    for it in body:
        if not it.get("source") or not (it.get("pmid") or it.get("url")):
            errs.append(f"出典がありません: {it.get('topic')}")
        if it.get("pmid") and str(it["pmid"]) in st["used_sources"]:
            errs.append(f"過去に使った出典です: PMID {it['pmid']}（{it.get('topic')}）")
        if it.get("topic") in st["used_topics"]:
            errs.append(f"過去に使った話題です: {it.get('topic')}")
        if not (it.get("image") or it.get("image_query")):
            errs.append(f"絵の指定がありません: {it.get('topic')}")
    off = [it.get("topic") for it in body if it.get("category") != theme]
    if off:
        errs.append(f"今日のテーマ「{theme}」以外の雑学があります（category を確認）: {off}")
    if theme not in "".join(ln.get("caption", "") for ln in items[0].get("lines", [])):
        errs.append(f"導入の画面にテーマ「{theme}」が出ていません")
    if not 1100 <= total <= 1450:
        errs.append(f"読み上げの合計が{total}字です（1,150〜1,350字が目安）")
    if not sc.get("youtube", {}).get("title"):
        errs.append("youtube.title がありません")
    if errs:
        print("台本の検査で不合格:\n  " + "\n  ".join(errs))
        sys.exit(1)
    print(f"台本 OK: 雑学{len(body)}個・読み上げ{total}字")


def cmd_done(path: Path, url: str, by: str, key: str | None = None, keep_order: bool = False) -> None:
    sc = json.loads(path.read_text(encoding="utf-8"))
    body = sc["items"][1:-1]
    day = key or today()

    def change(st):
        st["used_topics"] += [it["topic"] for it in body if it.get("topic")]
        st["used_sources"] += [str(it["pmid"]) for it in body if it.get("pmid")]
        st["done"][day] = {"url": url, "by": by, "title": sc.get("youtube", {}).get("title"),
                           "theme": sc.get("theme"),
                           "fixed": keep_order or st.get("theme_overrides", {}).get(day) == sc.get("theme")}
        st["claims"].pop(day, None)
    st = update_shared(change, f"{day} 投稿: {url}")
    print(f"記録しました: {day} → {url}（使用済みの話題 {len(st['used_topics'])}件）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pull", "claim", "release", "check", "done", "theme", "skip-theme",
                                    "extra"])
    ap.add_argument("--skip", default="", help="extra と一緒に使う。ネタがそろわず外すテーマ（カンマ区切り）")
    ap.add_argument("script", nargs="?")
    ap.add_argument("--url", default="")
    ap.add_argument("--by", default="mac", choices=["mac", "cloud"])
    ap.add_argument("--scope", action="store_true", help="theme と一緒に使う。テーマの範囲の説明も出す")
    ap.add_argument("--theme", help="check と一緒に使う。今日のテーマの代わりにこのテーマで検査する（追加の回）")
    ap.add_argument("--key", help="done と一緒に使う。台帳の記録先（追加の回は「日付-extraN」）")
    ap.add_argument("--keep-order", action="store_true",
                    help="done と一緒に使う。毎日の回のテーマの順番を進めない（ルーティンとは別に作った回）")
    a = ap.parse_args()
    if a.cmd == "pull":
        cmd_pull()
    elif a.cmd == "skip-theme":
        cmd_skip_theme()
    elif a.cmd == "theme":
        st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else read_shared()
        t = theme_for(st, today())
        print(f"{t}（範囲: {THEME_SCOPE[t]}）" if a.scope else t)
    elif a.cmd == "extra":
        # 毎日の2本目: 記録先のキーとテーマを1行ずつ出す（台帳は共有のものを読む）
        st = read_shared()
        t = next_theme(st, {s for s in a.skip.split(",") if s})
        print(next_extra_key(st, today()))
        print(f"{t}（範囲: {THEME_SCOPE[t]}）" if a.scope else t)
    elif a.cmd == "claim":
        cmd_claim(a.by)
    elif a.cmd == "release":
        cmd_release(a.by)
    elif a.cmd == "check":
        check(Path(a.script), a.theme)
    else:
        cmd_done(Path(a.script), a.url, a.by, a.key, a.keep_order)


if __name__ == "__main__":
    main()

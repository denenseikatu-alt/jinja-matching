"""Gemini の音声生成（TTS）で1文を WAV にする。

    GEMINI_API_KEY を環境変数に置いておく。
    声（prebuilt voice）と読み方の指示は台本の "voice" ブロックで変えられる:
        "voice": {"engine": "gemini", "name": "Leda",
                  "style": "Say in a bright, friendly young woman's voice"}

style は英語で書く。「指示: 本文」の形で送ると本文だけが読まれる
（日本語で指示を書くと、指示文まで読み上げてしまうことを文字起こしで確認した）。

モデル名は GEMINI_TTS_MODEL で指定できる（カンマ区切りで複数書くと、1日の無料枠を
使い切ったときに次のモデルへ切り替える）。指定がなく既定のモデルが無い場合は、
使えるモデルの一覧から名前に "tts" を含むものを選ぶ。
"""

from __future__ import annotations

import base64
import http.client
import json

import numpy as np
import os
import sys
import time
import urllib.error
import urllib.request

import video_env

video_env.load()
import wave
from pathlib import Path

API = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
RATE = 24000
_model_cache: str | None = None
_exhausted: set[str] = set()      # 今日の無料枠を使い切ったモデル
QUOTA_EXIT = 75                   # 1日の無料枠を使い切ったときの終了コード


def _key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY がありません（Gemini の音声生成に必要です）。")
    return key


def _request(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "x-goog-api-key": _key(), "Content-Type": "application/json"})
    # 通信が途中で切れたとき（相手が応答せずに切った・時間切れ）は、少し待って繰り返す
    # （2026-10-20 全サイト紹介動画の書き出しが RemoteDisconnected で止まったため）。
    # HTTP のエラー（402・429 など）は呼び出し側で扱うので、そのまま返す
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError) as e:
            if attempt == 4:
                raise
            print(f"    通信が切れました（{type(e).__name__}）。{20 * (attempt + 1)}秒後に繰り返します", flush=True)
            time.sleep(20 * (attempt + 1))


def pick_model() -> str:
    global _model_cache
    if _model_cache:
        return _model_cache
    wanted = [m.strip() for m in os.environ.get("GEMINI_TTS_MODEL", "").split(",") if m.strip()]
    wanted = [m for m in wanted if m not in _exhausted]
    if wanted:
        _model_cache = wanted[0]
        return _model_cache
    names = []
    token = ""
    while True:
        page = _request(f"{API}/models?pageSize=200" + (f"&pageToken={token}" if token else ""))
        names += [m["name"].split("/", 1)[1] for m in page.get("models", [])]
        token = page.get("nextPageToken", "")
        if not token:
            break
    tts = [n for n in names if "tts" in n]
    if not tts:
        sys.exit("このキーで使える Gemini の音声生成モデルが見つかりません。")
    _model_cache = DEFAULT_MODEL if DEFAULT_MODEL in tts else sorted(tts)[-1]
    return _model_cache


def _generate(prompt: str, voice: str) -> bytes:
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    for attempt in range(8):
        try:
            res = _request(f"{API}/models/{pick_model()}:generateContent", body)
            part = res["candidates"][0]["content"]["parts"][0]["inlineData"]
            return _strip_tail_junk(base64.b64decode(part["data"]))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code == 429 and "PerDay" in detail:
                # 1日の枠を使い切った。次の候補があれば切り替え、なければ止める
                global _model_cache
                _exhausted.add(pick_model())
                _model_cache = None
                left = [m for m in os.environ.get("GEMINI_TTS_MODEL", "").split(",")
                        if m.strip() and m.strip() not in _exhausted]
                if left:
                    print(f"    {sorted(_exhausted)[-1]} の今日の枠を使い切ったので {left[0].strip()} に切り替えます",
                          flush=True)
                    continue
                # 終了コード 75 で止める。呼び出し側（cloud/daily.sh）は途中までの音声を
                # 保存して、翌日の枠で続きを作る
                print("Gemini の音声生成の、今日の無料枠を使い切りました。", file=sys.stderr)
                try:
                    err = json.loads(detail)["error"]
                    print("  " + err["message"][:300], file=sys.stderr)
                    # どの上限に当たったか（1日の回数・1分の回数など）を残す
                    for x in err.get("details", []):
                        for v in x.get("violations", []):
                            print(f"  上限: {v.get('quotaId')} = {v.get('quotaValue')}", file=sys.stderr)
                except Exception:
                    pass
                sys.exit(QUOTA_EXIT)
            if e.code == 402:
                # 前払いの残高が尽きた。オーナーが残高を足すまで作れないので、無料枠切れと同じく
                # 終了コード 75 で止めて台本を預け、次の日に続きから作る
                print("Gemini の前払いの残高がなくなりました（AI Studio で残高を足す必要があります）。",
                      file=sys.stderr)
                sys.exit(QUOTA_EXIT)
            if e.code in (429, 500, 503) and attempt < 7:
                wait = 10 * (attempt + 1)
                try:
                    for d in json.loads(detail)["error"].get("details", []):
                        if "retryDelay" in d:
                            wait = max(wait, float(d["retryDelay"].rstrip("s")) + 1)
                except Exception:
                    pass
                print(f"    Gemini {e.code}、{wait:.0f}秒待って再試行します", flush=True)
                time.sleep(wait)
                continue
            sys.exit(f"Gemini の音声生成に失敗しました（{e.code}）: {detail[:300]}")
        except (KeyError, IndexError):
            if attempt < 7:
                time.sleep(5)
                continue
            sys.exit(f"Gemini から音声が返りませんでした: {str(res)[:300]}")
    sys.exit("Gemini の音声生成に失敗しました")


def _strip_tail_junk(pcm: bytes) -> bytes:
    """Gemini の音声の末尾につく雑音を切り落とす。

    返ってくる音声の最後に、静かな区間のあと、ほぼ最大音量の雑音が 0.1〜0.2 秒つくことが
    ある（まとめて生成した回の最後の文で毎回確認した）。末尾0.6秒の中で、0.1秒以上
    静か（-45dB 未満）な区間のあとに大きな音（-20dB 超）が始まり、それが最後まで
    続いていれば、その大きな音の始まりで切る。
    """
    a = np.frombuffer(pcm, dtype=np.int16)
    x = a.astype(np.float32) / 32768
    win = int(RATE * 0.01)
    n = len(x) // win
    if n < 20:
        return pcm
    db = 20 * np.log10(np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1)) + 1e-9)
    loud = db > -20
    # 末尾から、大きな音が続く区間の始まりを探す
    k = n
    while k > 0 and loud[k - 1]:
        k -= 1
    burst = n - k
    if burst == 0 or burst > 60 or k < 10:     # 末尾が静か、または0.6秒より長い大音量は対象外
        return pcm
    if np.all(db[k - 10:k] < -45):              # 直前0.1秒が静か → 話し声の続きではない
        return a[: k * win].tobytes()
    return pcm


def _write(pcm: bytes, out_path: Path) -> None:
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def synth(text: str, out_path: Path, voice: str = "Leda", style: str = "") -> None:
    """1文を1回の生成で作る。"""
    pcm = _generate(f"{style}: {text}" if style else text, voice)
    _write(_trim(pcm), out_path)


def synth_lines(lines: list[str], out_paths: list[Path], voice: str = "Leda",
                style: str = "") -> None:
    """複数の文を1回の生成でまとめて読ませ、息継ぎの無音で文ごとに切り分ける。

    無料枠は1日あたりの回数制限が厳しいため（モデルごとに10回など）、
    1文ずつではなく数場面分をまとめて頼む。
    """
    # 指示に余計な語を足すと、指示文そのものを読み上げることがあった（文字起こしで確認）。
    # 1文ずつのときに問題のなかった「指示: 本文」の形のままにする。
    directive = style or "Read aloud"
    # 指示文を読み上げるかどうかは毎回ばらつくので、何度か作り直す。
    # 文が多いまとまりは、切り分けがずれ続けたら半分ずつに分けて作り直す
    tries = 6 if len(lines) <= 3 else 3
    for attempt in range(tries):
        # 空行で区切ると、文と文の間の間（ま）がはっきりして切り分けやすい
        pcm = _generate(directive + ":\n\n" + "\n\n".join(lines), voice)
        a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        segs = _split(a, [len(x) for x in lines])
        problem = verify(lines, segs)
        if problem and problem.startswith("1文目に英語"):
            # 先頭で指示文を読んでいる。短い文のまとまりで起きやすく、作り直しても
            # 繰り返すので、指示文ぶんの区間を先頭に見込んで切り分け直し、それを捨てる
            for lead in (40, 30, 55):
                segs2 = _split(a, [lead] + [len(x) for x in lines])[1:]
                p2 = verify(lines, segs2)
                if p2 == "":
                    print("    先頭で読まれた指示文を切り落としました", flush=True)
                    segs, problem = segs2, ""
                    break
        if problem is None:
            # 照合用の文字起こしが混雑などで使えなかった。少し待って照合だけやり直す
            # （音声は作り直さない）。それでも使えなければ、全文を作り終えたあとの最終確認に回す
            for wait in (30, 90):
                time.sleep(wait)
                problem = verify(lines, segs)
                if problem is not None:
                    break
            if problem is None:
                print("    注意: 文字起こしが使えず、この部分は最後にもう一度照合します", flush=True)
                break
        if not problem:
            break
        print(f"    音声の照合で不一致: {problem}（作り直します）", flush=True)
    else:
        if len(lines) > 3:
            half = len(lines) // 2
            print(f"    {len(lines)}文のまとまりを {half}文と{len(lines) - half}文に分けて作り直します", flush=True)
            synth_lines(lines[:half], out_paths[:half], voice, style)
            synth_lines(lines[half:], out_paths[half:], voice, style)
            return
        sys.exit(f"Gemini の音声が台本と一致しませんでした: {problem}")
    for seg, path in zip(segs, out_paths):
        _write(seg, path)


def _norm(t: str) -> str:
    import re
    import unicodedata
    t = unicodedata.normalize("NFKC", t).replace("パーセント", "%")
    return re.sub(r"[\s、。，．,.!?！？「」『』（）()・:：]", "", t)


def verify(lines: list[str], segs: list[bytes]) -> str | None:
    """切り分けた各文を文字起こしし、台本と照合する。

    問題がなければ空文字、問題があればその内容、照合できなければ None を返す。
    """
    import difflib
    import io
    parts = [{"text": "以下の音声をそれぞれ一字一句そのまま文字起こししてください。"
                      "英語が含まれていれば、日本語に訳さず英語のまま書くこと。"
                      "また、その音声に英語（英単語や英文）が話されている部分が少しでもあれば english を true にすること。"
                      "出力は JSON のみで、キーは番号の数字: "
                      "{\"1\": {\"text\": \"…\", \"english\": false}, …}"}]
    for k, seg in enumerate(segs, 1):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(seg)
        parts += [{"text": f"{k}:"},
                  {"inlineData": {"mimeType": "audio/wav",
                                  "data": base64.b64encode(buf.getvalue()).decode()}}]
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json"}}
    got = None
    for model in ("gemini-3.5-flash", "gemini-flash-latest", "gemini-3-flash-preview"):
        for _ in range(3):
            try:
                res = _request(f"{API}/models/{model}:generateContent", body)
                got = json.loads(res["candidates"][0]["content"]["parts"][0]["text"])
                break
            except (urllib.error.HTTPError, KeyError, ValueError):
                time.sleep(8)
        if got is not None:
            break
    if got is None:
        return None
    import re
    heard, eng = {}, {}
    if isinstance(got, list):
        # まれに {"1": …} ではなく [{…}, {…}] の一覧で返ることがある（番号のキーがあればそれを使う）
        if len(got) == 1 and isinstance(got[0], dict) and all(re.search(r"\d", str(k)) for k in got[0]):
            got = got[0]
        else:
            got = {str(k): v for k, v in enumerate(got, 1)}
    if not isinstance(got, dict):
        return None
    for key, val in got.items():
        m = re.search(r"\d+", str(key))
        if m:
            if isinstance(val, dict):
                heard[int(m.group())] = str(val.get("text", ""))
                eng[int(m.group())] = bool(val.get("english"))
            else:
                heard[int(m.group())] = str(val)
    for k, line in enumerate(lines, 1):
        h = heard.get(k, "")
        # 文字起こし役が「英語が話されている」と答えたら、台本に英語の語がない限り作り直す
        # （英語を日本語に訳して書き起こされると、下の英単語の数え方では見落とすため）
        # ただし外来語（カタカナ語）や「ドットコム」を英語と答えることがあるので、書き起こしが台本とよく合い
        # 英字も出ていなければ数えない
        if eng.get(k) and not re.search(r"[A-Za-z]{3,}", line) and "ドットコム" not in line:
            close = difflib.SequenceMatcher(None, _norm(line), _norm(h)).ratio() >= 0.85
            letters = re.findall(r"[a-z]{3,}", re.sub(r"[A-Za-z][A-Za-z.\-]*\.(?:com|jp|net|org)(?![A-Za-z])", "", h))
            if letters or not close:
                return f"{k}文目に英語が話されている（{h[:40]}）"
        # 指示文を読んだときは英語の単語が混ざる。大文字だけの略語（ビーディーエヌエフ →
        # BDNF のように、カタカナで読ませた語を英字で書き起こしたもの）は数えない
        # サイト名（でんえんせいかつドットコム → denenseikatsu.com）のようなドメイン名も数えない
        # 直後に日本語が続く（「….comでは」）と \b が効かないので、英字が続かないことで判定する
        h_words = re.sub(r"[A-Za-z][A-Za-z.\-]*\.(?:com|jp|net|org)(?![A-Za-z])", "", h)
        words = [w for w in re.findall(r"[A-Za-z]{4,}", h_words) if not w.isupper()]
        if words and not re.search(r"[A-Za-z]{4,}", line):
            return f"{k}文目に英語が入っている（{h[:40]}）"
        # アドレスの文は、書き起こしが英字（denenseikatsu.com など）になり、短い文だと一致率が下がるので、
        # かなのアドレスと英字のアドレスを、どちらも「ドットコム」にそろえて比べる
        line_c = re.sub(r"[ぁ-んァ-ヶー]+ドットコム", "ドットコム", line)
        h_c = re.sub(r"[A-Za-z一-龥][A-Za-z一-龥.\-]*\.com(?![A-Za-z])", "ドットコム", h)
        ratio = difflib.SequenceMatcher(None, _norm(line_c), _norm(h_c)).ratio()
        if ratio < 0.6:
            return f"{k}文目が台本と合わない（一致率 {ratio:.2f}: {h[:30]}）"
    return ""


def _split(a: np.ndarray, lengths: list[int]) -> list[bytes]:
    """まとめて読ませた音声を、各文の文字数に合わせて無音で切り分ける。"""
    bounds = [0] + _find_cuts(a, lengths) + [len(a)]
    return [_trim((a[bounds[k]:bounds[k + 1]] * 32767).astype(np.int16).tobytes())
            for k in range(len(lengths))]


def _find_cuts(a: np.ndarray, lengths: list[int]) -> list[int]:
    """文字数の比から各文の境目のおよその時刻を出し、そこに近い無音で切る。"""
    win = int(RATE * 0.02)
    n = len(a) // win
    rms = np.sqrt((a[: n * win].reshape(n, win) ** 2).mean(axis=1))
    silent = rms < max(0.008, rms.max() * 0.03)
    # 0.14秒以上続く無音を切れ目の候補にする（中央で切る）
    gaps, run = [], 0
    for i, sv in enumerate(list(silent) + [False]):
        if sv:
            run += 1
        elif run:
            if run * win >= RATE * 0.14:
                gaps.append(((i - run / 2) * win, run * win / RATE))
            run = 0
    loud = np.where(~silent)[0]
    t0, t1 = loud[0] * win, (loud[-1] + 1) * win
    K = len(lengths) - 1
    if K <= 0:
        return []
    rate = (t1 - t0) / max(sum(lengths), 1)            # 1文字あたりのサンプル数
    scale = rate * 6                                    # 約6文字ぶんのずれを1とする
    C = len(gaps)
    if C < K:
        acc, cuts = 0, []
        for L in lengths[:-1]:
            acc += L
            cuts.append(int(t0 + rate * acc))
        return cuts
    pos = [g[0] for g in gaps]
    bonus = [1.5 * min(g[1], 1.0) for g in gaps]

    def seg(k: int, a: float, b: float) -> float:
        """k 番目の文の長さが、文字数から見込む長さにどれだけ近いか。"""
        return abs((b - a) - lengths[k] * rate) / scale

    # 動的計画法: 各文の長さが文字数に見合い、切れ目の無音は長いほど好ましい
    INF = float("inf")
    cost = [[INF] * C for _ in range(K)]
    back = [[-1] * C for _ in range(K)]
    for j in range(C):
        cost[0][j] = seg(0, t0, pos[j]) - bonus[j]
    for k in range(1, K):
        for j in range(k, C):
            best, arg = INF, -1
            for i in range(k - 1, j):
                v = cost[k - 1][i] + seg(k, pos[i], pos[j])
                if v < best:
                    best, arg = v, i
            cost[k][j] = best - bonus[j]
            back[k][j] = arg
    j = min(range(K - 1, C), key=lambda x: cost[K - 1][x] + seg(K, pos[x], t1))
    picks = []
    for k in range(K - 1, -1, -1):
        picks.append(int(pos[j]))
        j = back[k][j]
    return picks[::-1]


def _trim(pcm: bytes, margin: float = 0.08) -> bytes:
    """前後の無音を詰める。文と文の間は台本側の間（0.35秒など）で揃えるため。"""
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    win = int(RATE * 0.02)
    n = len(a) // win
    if n == 0:
        return pcm
    rms = np.sqrt((a[: n * win].reshape(n, win) ** 2).mean(axis=1))
    loud = np.where(rms > max(0.01, rms.max() * 0.03))[0]
    if loud.size == 0:
        return pcm
    start = max(0, loud[0] * win - int(RATE * margin))
    end = min(len(a), (loud[-1] + 1) * win + int(RATE * margin))
    seg = a[start:end].copy()
    # 切り口で波形が途切れるとプツッと鳴るので、頭と終わりを短くフェードさせる
    fade = min(int(RATE * 0.015), len(seg) // 4)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        seg[:fade] *= ramp
        seg[-fade:] *= ramp[::-1]
    return (seg * 32767).astype(np.int16).tobytes()


def synth_script(scenes: list[dict], audio_dir: Path, voice: dict, chunk_chars: int = 600) -> None:
    """台本の全文を、場面をまたがない約600字ずつにまとめて生成し、audio/0001.wav… に置く。

    すでにある文のファイルは作り直さない（途中で止まっても、翌日などに続きから作れる）。
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    chunk, count, k = [], 0, 0

    def flush(chunk):
        todo = [(line, audio_dir / f"{idx:04d}.wav") for idx, line in chunk]
        if any(not p.exists() for _, p in todo):
            synth_lines([l for l, _ in todo], [p for _, p in todo],
                        voice=voice.get("name", "Leda"), style=voice.get("style", ""))
            print(f"  音声 {todo[0][1].stem}〜{todo[-1][1].stem} を生成", flush=True)

    for s in scenes:
        scene_lines = []
        for line in s["lines"]:
            k += 1
            scene_lines.append((k, line))
        size = sum(len(l) for _, l in scene_lines)
        if chunk and count + size > chunk_chars:
            flush(chunk)
            chunk, count = [], 0
        chunk += scene_lines
        count += size
    if chunk:
        flush(chunk)
    final_check(scenes, audio_dir, voice)


def final_check(scenes: list[dict], audio_dir: Path, voice: dict, group: int = 8) -> None:
    """全文を作り終えたあと、文ごとの音声をもう一度まとめて文字起こしし、英語が混ざっていないか、
    台本と合っているかを確かめる。合わない文は1文ずつ作り直す（2026-10-16 オーナー指摘:
    ナレーションの一部が英語で読まれていた）。照合できないまま終わる場合は止める。"""
    if os.environ.get("TTS_FINAL_CHECK") == "0":
        # 試しの書き出し（前に確かめた音声を使い回すとき）だけ。公開する動画では使わない
        print("  最終確認を省きました（TTS_FINAL_CHECK=0）", flush=True)
        return
    lines = [l for s in scenes for l in s["lines"]]
    paths = [audio_dir / f"{k:04d}.wav" for k in range(1, len(lines) + 1)]

    def read(p: Path) -> bytes:
        with wave.open(str(p), "rb") as w:
            return w.readframes(w.getnframes())

    bad: list[int] = []
    for g in range(0, len(lines), group):
        idx = list(range(g, min(g + group, len(lines))))
        for attempt in range(4):
            problem = verify([lines[i] for i in idx], [read(paths[i]) for i in idx])
            if problem is not None:
                break
            time.sleep(30 * (attempt + 1))
        if problem is None:
            sys.exit("Gemini の音声を台本と照合できませんでした（文字起こしが使えない）。時間をおいて作り直してください")
        # 1文ずつ確かめて、合わない文を集める（まとめての照合は最初の1つしか返さないため）
        if problem:
            for i in idx:
                p1 = verify([lines[i]], [read(paths[i])])
                if p1:
                    bad.append(i)
    for i in bad:
        for attempt in range(5):
            print(f"    最終確認で不一致の {i + 1}文目を作り直します（{attempt + 1}回目）", flush=True)
            synth(lines[i], paths[i], voice=voice.get("name", "Leda"), style=voice.get("style", ""))
            if verify([lines[i]], [read(paths[i])]) == "":
                break
        else:
            sys.exit(f"Gemini の音声が台本と一致しませんでした（{i + 1}文目: {lines[i][:30]}）")
    print(f"  最終確認: 全{len(lines)}文を照合（作り直し {len(bad)}文）", flush=True)


def available(voice: str = "Leda") -> bool:
    """Gemini の声が今使えるか（前払いの残高切れ・1日の枠切れでないか）。短い1語を作って確かめる。"""
    if not os.environ.get("GEMINI_API_KEY"):
        return False
    try:
        _generate("Read aloud: はい。", voice)
        return True
    except SystemExit:
        return False


CREDIT = "音声: Google Gemini（AI 音声合成）"

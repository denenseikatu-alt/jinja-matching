# 引き継ぎ: 記事→動画パイプライン

クラウド実行のセッションで動画パイプラインを作ったが、**mp4 は未完成**。
この続きを、ユーザーの Mac 上（VOICEVOX が動く環境）で仕上げてほしい。

## 今の状態

パイプライン一式はこのブランチに入っていて、**手順は `VIDEO.md`** にある。

| ファイル | 状態 |
| --- | --- |
| `extract_article.py` | 完成・検証済み |
| `prompts/narration.md` | 完成 |
| `build_video.py` | 完成。ただし VOICEVOX 呼び出しのみ未検証 |
| `upload_youtube.py` | 完成。ただし YouTube API 送信のみ未検証 |
| `script.json` | **中身が間違っている。作り直しが必要**（下記） |

## やること

### 0. 事前チェック

```bash
bash preflight.sh
```

環境の不足を先に洗い出す。話者ID 10 のキャラクター名もここで確定する
（下記の「話者IDと名前が食い違っている」を参照）。

### 1. 台本を正しい記事で作り直す（必須）

`script.json` に入っている台本は `jinja-matching`（神社マッチング）のコラムから
作ったもので、**ユーザーが本来動画にしたい記事ではない**。

本来の対象は `denenseikatu.com`（田園生活サイト）のブログ記事。
クラウド環境では同ドメインが egress ポリシーで遮断されていて取得できなかったが、
**Mac からは普通にアクセスできるはず**。

まずユーザーにどの記事か確認し、記事URLを渡して抽出からやり直す:

```bash
python3 extract_article.py <記事URL> -o article.json
```

そのうえで `prompts/narration.md` のルールに従って `script.json` を書き直す。
既存の `script.json` の `scenes` は差し替え対象。`youtube` ブロックも記事に合わせて書き直す。

### 2. 書き出し

```bash
python3 build_video.py script.json -o out/
```

VOICEVOX ENGINE を起動しておくこと（既定 `http://127.0.0.1:50021`）。
終了時に実尺・スライド枚数・クレジットが表示される。

### 3. アップロード（ユーザーの指示を待つこと）

```bash
python3 upload_youtube.py out/video.mp4 --dry-run   # 内容確認
python3 upload_youtube.py out/video.mp4             # 非公開で送信
```

## 注意点

### 話者IDと名前が食い違っている

ユーザーは「話者ID 10 は**ヒロ**」と言っているが、クラウド側の認識では
ID 10 は「**雨晴はう**」で、確認が取れていない。VOICEVOX に到達できず検証できなかった。

`build_video.py` は `/speakers` から正式名称を引いて `out/credits.txt` に書く。
これが YouTube 概要欄のクレジットになる（VOICEVOX の規約がキャラクター名の明記を求めるため）。
**書き出し後に `out/credits.txt` を必ず目視確認し、ユーザーの認識と違えば指摘すること。**
名前が取れていない場合、`upload_youtube.py` は意図的にアップロードを中断する。

### 未検証の箇所

- `build_video.py` の `synth()` — VOICEVOX への HTTP 呼び出し。
- `upload_youtube.py` の送信部分 — 認証情報が無く未実行。

どちらも Mac での初回実行が実質的な初テストになる。失敗したら素直に報告すること。

検証済みなのは、記事抽出（6記事）、スライド描画、尺計算、字幕生成、ffmpeg 連結、
概要欄の組み立て（`--dry-run`）。

### やってはいけないこと

- **実尺を推定値で報告しない。** 尺は `build_video.py` が実測して表示する値を使う。
- **ユーザーの許可なくアップロードしない。**
- 出典ドメインを決め打ちしない（`extract_article.py` が canonical から取る）。

## 経緯

クラウド実行環境では、VOICEVOX（ユーザーのMac上）にも denenseikatu.com にも
到達できず、音声を1秒も合成できなかった。そのため「Mac 上の Claude Code で続ける」
という判断になった。関連 PR: #3（draft）。

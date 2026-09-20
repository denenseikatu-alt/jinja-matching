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
| `script.json` | **存在しない。作るのがこの作業の本体**（下記） |
| `examples/script.sample.json` | 書式の見本。神社記事のものなので内容は流用しない |

## やること

### 0. 事前チェック

```bash
bash preflight.sh
```

環境の不足を先に洗い出す。話者ID 10 のキャラクター名もここで確定する
（下記の「話者IDと名前が食い違っている」を参照）。

### 1. 台本を正しい記事で作り直す（必須）

かつて `script.json` に神社記事の台本が入っていたが、誤って書き出す事故を防ぐため
`examples/script.sample.json` に退避してある。**あれは書式の見本であって、内容は
ユーザーが動画にしたい記事ではない。** 中身は必ず作り直すこと。

**対象記事はユーザーから指定済み:**

```
https://denenseikatu.com/articles/post-exercise-calorie-burn-morning-vs-evening-waseda/
```

（運動後のカロリー消費、朝と夕方の比較、早稲田大学の研究に関する記事らしい。
神社とは全く別ジャンルなので、既存の台本は完全に捨てて作り直すこと。）

クラウド環境では `denenseikatu.com` が egress ポリシーで遮断されていて取得できなかったが、
**Mac からは普通にアクセスできるはず**。

```bash
python3 extract_article.py https://denenseikatu.com/articles/post-exercise-calorie-burn-morning-vs-evening-waseda/ -o article.json --dump
```

`--dump` で抽出結果を目視確認すること。**このサイトの HTML 構造は未確認**
（クラウドから到達できなかったため）。ナビやフッターの文字が本文に混ざっていたら、
`--skip "文字列"` や `--skip-sentence "文字列"` で除ける。

数字や研究機関名を扱う記事なので、**台本に記事にない数値・大学名・研究結果を足さないこと。**
読み違いが起きやすい単位（kcal、％など）は `prompts/narration.md` の方針に従って読みを開く。

そのうえで `prompts/narration.md` のルールに従って `script.json` を新規に書く。
書式は `examples/script.sample.json` を見ればよいが、`scenes` も `youtube` ブロックも
対象記事の内容で書き起こすこと。

narration.md には**数値・単位の扱い**と**研究結果の扱い**の節がある。
この記事は大学の研究を扱うので、そこは必ず読むこと（主張の強さを変えない、
被験者数や期間などの条件を落とさない、記事にない健康上の助言を足さない）。

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

### 話者IDの名前（決着済み）

**VOICEVOX ENGINE 0.25.2 で確認済み: 話者ID 10 = 雨晴はう / ノーマル。**
このエンジンに「ヒロ」という話者は存在しない（ヒロは記事の執筆者名）。
クレジットは `VOICEVOX:雨晴はう` になる。

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

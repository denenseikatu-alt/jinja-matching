# 記事 → 動画パイプライン

コラム記事から、ナレーション付きのスライド動画（mp4）と字幕（srt）を作る。

## 必要なもの

- Python 3.9 以上
- `pip install pillow`
- **VOICEVOX ENGINE**（起動しておく。既定 `http://127.0.0.1:50021`）
- ffmpeg（`pip install imageio-ffmpeg` でも代用可）

## 手順

### 1. 記事を抽出

```bash
python3 extract_article.py https://denenseikatu.com/column/sanpai-saho/
```

URL に対応する HTML がこのリポジトリ内にあればそれを読むので、
オフラインでも動く。`article.json` が出る。

### 2. 台本を書く

`article.json` をもとに、`prompts/narration.md` のルールに従って
`script.json` を作る。話者 ID は既定で **10**。

読み間違い対策（「正中」→「せいちゅう」など）は narration.md の表を参照。
画面に出す `bullets` は漢字のまま、読み上げる `lines` は読みを開いて書く。

### 3. 書き出し

```bash
# VOICEVOX を起動した状態で
python3 build_video.py script.json -o out/
```

`out/video.mp4`、`out/video.srt`、`out/slides/*.png` が出る。
終了時に尺とスライド枚数を表示する。

スライドの見た目だけ先に確認したいときは VOICEVOX なしで:

```bash
python3 build_video.py script.json -o out/ --slides-only
```

### 4. YouTube へ非公開アップロード

```bash
pip install google-auth-oauthlib google-api-python-client
python3 upload_youtube.py out/video.mp4 --dry-run   # 送信内容の確認
python3 upload_youtube.py out/video.mp4             # 実行
```

タイトル・概要欄・タグは `script.json` の `youtube` ブロックから取り、
概要欄の末尾に目次・記事URL・VOICEVOXのクレジットを自動で付ける。
既定は `privacyStatus: private`（非公開）。

初回は Google Cloud で YouTube Data API v3 を有効にし、「デスクトップアプリ」の
OAuth クライアントIDを `client_secret.json` として置く。実行するとブラウザで
認可を求められ、`token.json` が作られる。**どちらも `.gitignore` 済み。**

## 仕様のメモ

- `lines` の 1 要素 = 音声合成 1 回 = 字幕 1 枚。
- 字幕のタイムコードは、文字数からの推定ではなく**合成した wav の実長**から積み上げる。
  そのため音ズレしない。
- 文と文のあいだに 0.35 秒、スライドの切り替わりに 0.65 秒の無音を挟む
  （`build_video.py` の `GAP_AFTER_LINE` / `GAP_AFTER_SCENE`）。
- 出力は 1920×1080 / 30fps / H.264 + AAC。
- `out/chapters.txt` と `out/credits.txt` は書き出し時に作られ、概要欄の組み立てに使う。
  クレジットは VOICEVOX ENGINE の `/speakers` から話者IDに対応する**キャラクター名**を
  引いて書く（利用規約がキャラクター名の明記を求めるため、推測では書かない）。
  名前が取れていない場合、`upload_youtube.py` はアップロードを中断する。
- 日本語フォントは `FONT_CANDIDATES` から自動検出する
  （Linux の IPAGothic、macOS のヒラギノ、Windows の游ゴシック / メイリオ）。
  見つからない場合はリストにパスを足す。

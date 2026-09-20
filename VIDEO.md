# 記事 → 動画パイプライン

コラム記事から、ナレーション付きのスライド動画（mp4）と字幕（srt）を作る。

## 必要なもの

- Python 3.9 以上
- `pip install pillow`
- **VOICEVOX ENGINE**（起動しておく。既定 `http://127.0.0.1:50021`）
- ffmpeg（`pip install imageio-ffmpeg` でも代用可）

## 手順

### 0. 事前チェック

```bash
bash preflight.sh
```

Python・Pillow・ffmpeg・日本語フォント・VOICEVOX の疎通をまとめて確認し、
足りないものと直し方を出す。話者ID 10 に対応するキャラクター名もここで分かる。

### 1. 記事を抽出

```bash
python3 extract_article.py https://denenseikatu.com/column/sanpai-saho/
```

URL に対応する HTML がこのリポジトリ内にあればそれを読むので、
オフラインでも動く。`article.json` が出る。

### 2. 台本を書く

`article.json` をもとに、`prompts/narration.md` のルールに従って
`script.json` を作る。話者 ID は既定で **10**。
書式の見本は `examples/script.sample.json`（神社記事のもの。内容は流用しない）。

読み間違い対策（「正中」→「せいちゅう」など）は narration.md の表を参照。
画面に出す `bullets` は漢字のまま、読み上げる `lines` は読みを開いて書く。

### 3. 書き出し

```bash
# VOICEVOX を起動した状態で
python3 build_video.py script.json -o out/
```

`out/video.mp4`、`out/video.srt`、`out/slides/*.png` が出る。
終了時に尺とスライド枚数を表示する。

### VOICEVOX が手元に無い環境で動かす

ENGINE の配布物は直URLなら取得できる（リリースのHTMLページは 403 になるが、
`releases/download/<tag>/<file>` は通る）。Linux なら以下でこの場に立てられる:

```bash
V=0.25.2
curl -sSL -o engine.7z \
  "https://github.com/VOICEVOX/voicevox_engine/releases/download/$V/voicevox_engine-linux-cpu-x64-$V.7z.001"
pip install py7zr && python3 -c "import py7zr; py7zr.SevenZipFile('engine.7z').extractall()"
cd linux-cpu-x64 && ./run --host 127.0.0.1 --port 50021 &
```

配布物は約1.7GB、展開後を含めて4GB程度の空きが要る。起動に20秒ほどかかる。
タグ一覧は `git ls-remote --tags https://github.com/VOICEVOX/voicevox_engine` で取れる。

### ローカル完結の簡易合成

VOICEVOX をどうしても用意できない場合の代替:

```bash
pip install pyopenjtalk numpy
python3 build_video.py script.json -o out/ --engine openjtalk
```

外部接続なしで動くが、声質は素朴な合成音になる（VOICEVOX の代わりにはならない）。
使用する HTS 音声「Mei」は CC BY 3.0 で表示が義務のため、クレジットは自動で入る。

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
- 日本語フォントは自動検出する。まず `FONT_CANDIDATES` の決め打ちパスを見て、
  外れたら `FONT_DIRS` を再帰的に探す（macOS はヒラギノの場所がOSバージョンで
  変わるため、名前で拾う）。それでも見つからないときは `--font` で直接指定する:

  ```bash
  python3 build_video.py script.json -o out/ --font '/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc'
  ```

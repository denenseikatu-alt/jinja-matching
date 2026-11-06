# 毎日1本の手順

denenseikatu.com の過去記事を、1日1本ずつ動画にして YouTube に非公開でアップする。
Mac 上の Claude Code セッションがこの手順を実行する。

## 前提

- VOICEVOX ENGINE が起動していること（既定 `http://127.0.0.1:50021`）
- `client_secret.json` と `token.json` が `~/jinja-matching/` にあること
- サイトのローカルコピーが `~/Downloads/denenseikatu-site` にあること
- 仮想環境が有効なこと（`source .venv/bin/activate`）

`bash preflight.sh` で1〜2は確認できる。

## 手順

### 1. 今日の記事を選ぶ

```bash
python3 pick_article.py
```

スラッグ・パス・URL・進捗が出る。**まだ処理済みとして記録はされない。**

### 2. 記事を抽出する

```bash
python3 extract_article.py <手順1で出たパス> -o article.json --dump
```

`--dump` の出力を必ず目視する。ナビやフッターの文字が本文に混ざっていたら
`--skip "文字列"` や `--skip-sentence "文字列"` で除いてやり直す。

### 3. 台本を書く

`article.json` をもとに `prompts/narration.md` のルールに従って `script.json` を作る。
書式は `examples/script.sample.json` を参照（内容は流用しない）。

**この記事群は健康・運動・栄養の話題で、研究データを扱うものが多い。**
narration.md の「数値とデータの扱い」「研究・出典の扱い」を必ず読むこと。要点:

- 記事にある数値だけを使い、丸めや言い換えをしない
- 記事の主張の強さを変えない（「傾向」を「証明」にしない）
- 被験者数・期間・対象者の属性などの条件を落とさない
- **記事にない健康上の助言を足さない**
- 概要欄に「一般的な参考情報であり、医師による診断・治療に代わるものではない」旨を入れる

`script.json` の `source_url` と `site_host` は抽出結果のものを使う。話者IDは 9（波音リツ）。

### 4. 書き出す

```bash
python3 build_video.py script.json -o out/
```

実尺・スライド枚数・クレジットが表示される。**尺は推定せず、この表示値を使う。**

### 5. アップロードする

```bash
python3 upload_youtube.py out/video.mp4 --dry-run   # 内容確認
python3 upload_youtube.py out/video.mp4             # 非公開で送信
```

### 6. 記録する

```bash
python3 pick_article.py --done <スラッグ> --url <表示された動画URL>
```

**これを忘れると翌日も同じ記事を選んでしまう。**

## 失敗したとき

- 途中で止まったら `--done` を記録しないこと。翌日また同じ記事から再開する。
- VOICEVOX に繋がらない → 起動を確認。`preflight.sh` で切り分け。
- 認可エラー → `token.json` を削除して `upload_youtube.py` を手で1回実行し、再認可する。
  OAuth同意画面が「テスト」状態だとリフレッシュトークンが7日で失効する。
  毎週切れるようなら同意画面を「本番」に切り替える必要がある。

## 進捗の確認

```bash
python3 pick_article.py --status
```

台帳は `video_state.json`。処理済みのスラッグ・日付・動画URLが入っている。

## 毎日自動で走らせる

`daily_run.sh` が、VOICEVOX の起動確認から Claude Code の実行までを一括で行う。
まず手で一度動かして確かめる。

```bash
bash ~/jinja-matching/daily_run.sh
tail -f ~/jinja-matching/logs/$(date +%Y-%m-%d).log
```

うまくいったら launchd に登録して、毎朝9時に走らせる。

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.denen.dailyvideo.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.denen.dailyvideo</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$HOME/jinja-matching/daily_run.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
PLIST

launchctl unload ~/Library/LaunchAgents/com.denen.dailyvideo.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.denen.dailyvideo.plist
```

止めるときは `launchctl unload ~/Library/LaunchAgents/com.denen.dailyvideo.plist`。

### 注意

- **Macが起動している必要がある。** スリープ中は走らない。その日は飛ばされ、翌日に同じ記事から再開する。
- ログは `logs/YYYY-MM-DD.log`。失敗した日はここを見る。
- OAuth同意画面が「テスト」状態だと、リフレッシュトークンが7日で失効する。
  毎週認可を求められるようなら、同意画面を「本番」に切り替える必要がある。
- **公開設定は `PRIVACY` で決まる（既定 `public`）。** 非公開に戻すなら
  `PRIVACY=private bash daily_run.sh`、または daily_run.sh の既定値を変える。
- **審査前のAPIプロジェクトからのアップロードは、YouTube側で非公開に固定される。**
  `--privacy public` を指定しても非公開のまま上がることがある。その場合は
  Google Cloud Console でAPIプロジェクトの審査を申請するか、YouTube Studio で
  1本ずつ公開に切り替える。

# クラウド版の毎日1本（Mac 不要）

Claude Code のクラウド実行環境で、記事の取得から YouTube への公開までを行う。
Mac が手元になくても、電源が切れていても動く。

## 仕組み

| 工程 | 担当 |
| --- | --- |
| VOICEVOX ENGINE の取得・起動 | `cloud/setup.sh`（毎回ダウンロードして起動。約2分） |
| 記事選び | `pick_article.py --sitemap ... --youtube`。サイトの sitemap から記事一覧を取り、**YouTube に投稿済みの動画の概要欄にある記事URL** を処理済みとみなす。台帳ファイルは使わない |
| 抽出 | `extract_article.py`（サイトの WAF に弾かれないよう、名乗りを付けた User-Agent で取得） |
| 台本 | ルーティンのセッション（Claude）が `prompts/narration.md` に従って書く |
| 書き出し・投稿 | `cloud/daily.sh publish` |

`cloud/daily.sh prepare` → 台本 → `cloud/daily.sh publish` の順に動く。

二重投稿の防止:
- 直近20時間以内に記事動画を上げていたら、その日は何もしない
- 送信の直前にも、その記事が投稿済みでないかを YouTube で確かめる

## 必要な設定（クラウド環境の設定画面）

claude.ai/code の入力欄の上にある雲のアイコン → 環境の歯車 から開く。

1. **Network access**: Custom にして、Allowed domains に `denenseikatu.com` を追加。
   「Also include default list of common package managers」にチェック
   （VOICEVOX や Python パッケージの取得に要る）
2. **Environment variables**: 次の3行（値は `yt_auth.py` で作る）
   ```
   YT_CLIENT_ID=...
   YT_CLIENT_SECRET=...
   YT_REFRESH_TOKEN=...
   ```

### YouTube の認可（初回のみ。スマホでできる）

```bash
YT_CLIENT_ID=... YT_CLIENT_SECRET=... python3 yt_auth.py url
```

出た URL をブラウザで開いて許可する。最後に `localhost` のページが開けずに終わるが、
それで正しい。そのときのアドレスバーの URL を丸ごと渡す:

```bash
YT_CLIENT_ID=... YT_CLIENT_SECRET=... python3 yt_auth.py exchange 'http://localhost:8765/?...'
```

表示された3行を Environment variables に入れる。`python3 yt_auth.py check` で確認できる。

Google Auth Platform の「対象（Audience）」が**テスト中のままだと、認可が7日で切れる**。
「アプリを公開」で本番にしておくこと。

## Mac 版との関係

Mac の launchd ジョブ（`daily_run.sh`）も動いていると、同じ日に2本上がることがある。
クラウド版に一本化するなら、Mac で次を実行して止める:

```bash
launchctl unload ~/Library/LaunchAgents/com.denen.dailyvideo.plist
```

クラウド版は YouTube 側を見て判断するので、Mac で上げた記事を重ねて上げることはない。

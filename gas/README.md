# 独自アナリティクス — 自己アクセス除外

自分の Mac・Claude Code 内蔵ブラウザ・ローカルプレビューからのアクセスを
独自アナリティクス（GAS ウェブアプリ）の集計から外すための変更一式。

## 除外の三段構え

| 段 | 場所 | 何を止めるか |
|---|---|---|
| 1 | 各 HTML の `da-optout v3` ブロック（`<head>` 先頭） | 判定して `window.__DA_SELF__` を立て、GA4 を無効化し、`script.google.com/macros` 宛の `sendBeacon` / `XHR` を握り潰す |
| 2 | 各 HTML の計測タグ先頭 | `if (window.__DA_SELF__) return;` で送信処理自体を実行しない |
| 3 | GAS `doPost` の `isSelfAccess_()` | 1・2 をすり抜けた分を UA・host で弾く（二重フィルタ） |

### 除外条件（1 と 2 で共通、判定は 1 箇所だけ）

- `localStorage.noga === '1'`（旧 `_da_optout === '1'` も引き続き有効）
- ホスト名が `localhost` / `127.0.0.1` / `[::1]`
- ホスト名が `*.pages.dev`（Cloudflare Pages のプレビュー）
- `navigator.webdriver === true`（Playwright / Selenium）
- UA が `Headless|Puppeteer|Playwright|Electron`

`?noga=1` で除外 ON、`?noga=0` で解除。旧来の `?optout=1` / `?optout=0` も
同じ意味で動き続けるので、既に除外設定済みの端末はそのままでよい。

判定ロジックは `<head>` のブロック 1 箇所にだけ置いてある。計測タグ側は
その結果（`window.__DA_SELF__`）を見るだけなので、条件が重複していない。

## 送信ペイロードの追加項目

GAS 側の二重フィルタ用に 2 項目を追加した。

- `ua`   … `navigator.userAgent`
- `host` … `location.hostname`

## GAS への導入

`analytics-guard.gs` の冒頭コメントに手順あり。要点だけ:

1. GAS プロジェクトに **新しいファイル** として `analytics-guard.gs` を追加
   （既存 `Code.gs` は書き換えない）
2. `LOG_SHEET_NAME` を実際のログシート名に合わせる
3. 既存 `doPost` に 1 行だけ追加:
   ```js
   if (isSelfAccess_(d)) return ContentService.createTextOutput('skipped');
   ```
4. ダッシュボードの集計ループに 1 行追加:
   ```js
   const idx = getColumnIndex_(sheet);          // ループの外で 1 回
   if (isExcludedRow_(row, idx)) return;        // ループの中で
   ```
   `isExcludedRow_` は `excluded === true` を弾くほか、`excluded` 列が
   まだ無い行も UA・host で判定するので、遡及処理の前でも安全に使える。

## 既存データの遡及除外

行は **一切削除しない**。`excluded` 列に `TRUE` を立てるフラグ方式。

- `purgeSelfAccess()` — UA・host のパターンに一致する行に `TRUE`。
  何度実行しても安全（列も重複しない）。
- `purgeByVisitorId(['xxx','yyy'])` — visitor ID を指定して除外。
- `listTopVisitors()` — アクセス数上位の visitor ID を表示。

> **注意**: `ua` / `host` は今回の変更以降に記録される行にしか入らない。
> それ以前の自分のアクセスは UA では特定できないので、
> `purgeByVisitorId()` を使うこと。自分の ID は各ブラウザの DevTools で
> `localStorage.getItem('_da_vid')` を実行すると取れる。

## 手動でやる作業のチェックリスト

### GAS 側

- [ ] `analytics-guard.gs` を GAS プロジェクトに新規ファイルとして貼り付け
- [ ] `LOG_SHEET_NAME` を実際のシート名に修正
- [ ] `doPost` に `isSelfAccess_` の 1 行を追加
- [ ] ダッシュボードの集計に `isExcludedRow_` の条件を追加
- [ ] **「デプロイを管理」→ 鉛筆 →「新しいバージョン」→ デプロイ**
      （「新しいデプロイ」にすると `/exec` の URL が変わって計測が止まるので不可）
- [ ] `purgeSelfAccess()` を 1 回実行し、実行ログで件数を確認
- [ ] 各ブラウザで `localStorage.getItem('_da_vid')` を控えて
      `purgeByVisitorId([...])` を実行

### ブラウザ側（端末・ブラウザごとに 1 回ずつ）

- [ ] Mac の Safari で `https://denenseikatu.com/?noga=1`
- [ ] Mac の Chrome で `https://denenseikatu.com/?noga=1`
- [ ] その他ふだん使うブラウザ・プロファイル（シークレットは毎回必要）
- [ ] iPhone など他端末でも同様に
- [ ] 解除したくなったら `?noga=0`

> localhost / `*.pages.dev` / ヘッドレス / Claude Code 内蔵ブラウザは
> フラグ無しで自動的に除外されるので、`?noga=1` を踏む必要はない。

### 確認

- [ ] 本番を普通に開き、DevTools の Network に `/exec` への POST が出ること
- [ ] `?noga=1` を踏んだ後にリロードし、POST が出ないこと
- [ ] スプレッドシートに `ua` / `host` 列が入った行が増えること
- [ ] ダッシュボードの数字が `excluded` 分だけ減っていること

### デプロイ

- [ ] 本番へのデプロイは**承認後**に実施（この変更では未実施）
- [ ] `gas/` を公開したくない場合はデプロイ対象から除外する
      （静的ホスティングは配下を全部配信するため、
      `denenseikatu.com/gas/analytics-guard.gs` で読めてしまう。
      認証情報は含めていないが、公開したくなければ要除外）

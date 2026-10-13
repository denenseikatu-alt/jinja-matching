/**
 * analytics-guard.gs — 自己アクセス除外ガード
 *
 * 既存の Code.gs は書き換えず、このファイルを GAS プロジェクトに
 * 「新しいファイル」として追加してください。
 * 既存側への変更は doPost の 1 箇所のみです（下記「導入手順」参照）。
 *
 * ── 導入手順 ────────────────────────────────────────────────
 * 1. GAS エディタで ＋ → スクリプト → 名前を "analytics-guard" にして
 *    このファイルの内容をそのまま貼り付ける。
 * 2. 既存 Code.gs の doPost の、シートへ書き込む処理より前に 1 行追加：
 *
 *      function doPost(e){
 *        const d = JSON.parse(e.postData.contents);
 *        if (isSelfAccess_(d)) return ContentService.createTextOutput('skipped');  // ← これを追加
 *        // …既存の追記処理…
 *      }
 *
 * 3. LOG_SHEET_NAME を実際のログシート名に合わせる。
 * 4. 「デプロイ」→「デプロイを管理」→ 鉛筆 →「新しいバージョン」→ デプロイ。
 *    ※ /exec の URL は変わりません（新規デプロイにすると URL が変わるので不可）。
 * ───────────────────────────────────────────────────────────
 */

/** ログを書き込んでいるシート名。実際の名前に合わせて変更すること。 */
const LOG_SHEET_NAME = 'log';

/** 除外列のヘッダー名。 */
const EXCLUDED_HEADER = 'excluded';

/** 自分・ボット・自動化ブラウザの User-Agent */
const BLOCK_UA = /Headless|Puppeteer|Playwright|Electron|bot|crawler|spider|curl|wget|Google-Apps-Script/i;

/** 開発・プレビュー用ホスト（localhost / 127.0.0.1 / *.pages.dev） */
const BLOCK_HOST = /^(localhost|127\.0\.0\.1|\[::1\])$|\.pages\.dev$/i;


/**
 * 保存すべきでないアクセスかどうかを判定する。
 * クライアント側（da-optout v3）でも同じ判定をしているので、これは二重フィルタ。
 * @param {Object} d doPost で受け取った JSON
 * @return {boolean} true なら保存しない
 */
function isSelfAccess_(d) {
  if (!d) return true;
  if (d.noga === 1 || d.noga === '1') return true;
  if (BLOCK_UA.test(String(d.ua || ''))) return true;
  if (BLOCK_HOST.test(String(d.host || ''))) return true;
  return false;
}


/* ============================================================
 *  既存データの遡及除外
 * ============================================================ */

/**
 * ログシートに excluded 列を用意し、BLOCK_UA / BLOCK_HOST に一致する
 * 既存行に TRUE を立てる。行の削除は一切しない。
 *
 * GAS エディタで関数 purgeSelfAccess を選んで実行する。
 * 何度実行しても安全（冪等）。
 */
function purgeSelfAccess() {
  const sh = getLogSheet_();
  const lastRow = sh.getLastRow();
  if (lastRow < 2) { Logger.log('データ行がありません。'); return; }

  const col = ensureExcludedColumn_(sh);
  const headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0]
                    .map(function (h) { return String(h).trim().toLowerCase(); });
  const uaCol   = headers.indexOf('ua');
  const hostCol = headers.indexOf('host');

  if (uaCol === -1 && hostCol === -1) {
    Logger.log('ua 列も host 列も見つかりません。'
             + 'この場合 UA/host での遡及判定はできないため、'
             + 'purgeByVisitorId() を使ってください。');
    return;
  }

  const n    = lastRow - 1;
  const rows = sh.getRange(2, 1, n, sh.getLastColumn()).getValues();
  const cur  = sh.getRange(2, col, n, 1).getValues();
  const out  = [];
  let hit = 0, already = 0;

  for (let i = 0; i < n; i++) {
    const ua   = uaCol   === -1 ? '' : String(rows[i][uaCol]   || '');
    const host = hostCol === -1 ? '' : String(rows[i][hostCol] || '');
    const match = (ua && BLOCK_UA.test(ua)) || (host && BLOCK_HOST.test(host));
    if (cur[i][0] === true) already++;
    if (match) { hit++; out.push([true]); }
    else       { out.push([cur[i][0] === true ? true : cur[i][0]]); }  // 既存 TRUE は残す
  }

  sh.getRange(2, col, n, 1).setValues(out);
  Logger.log('走査 %s 行 / パターン一致 %s 行 / 実行前から除外済み %s 行', n, hit, already);
}


/**
 * visitor ID を指定して遡及除外する。
 *
 * ua / host はこの変更以降に記録された行にしか入っていないため、
 * それ以前の自分のアクセスは UA では特定できない。
 * 自分のブラウザの DevTools コンソールで
 *     localStorage.getItem('_da_vid')
 * を実行して出た ID を、ブラウザ・端末ごとに集めて渡すこと。
 *
 * 例: purgeByVisitorId(['abc123xyz', 'def456uvw'])
 *
 * @param {string[]} ids 除外したい visitor ID の配列
 */
function purgeByVisitorId(ids) {
  if (!ids || !ids.length) { Logger.log('ID が指定されていません。'); return; }
  const wanted = {};
  ids.forEach(function (v) { wanted[String(v).trim()] = true; });

  const sh = getLogSheet_();
  const lastRow = sh.getLastRow();
  if (lastRow < 2) { Logger.log('データ行がありません。'); return; }

  const col = ensureExcludedColumn_(sh);
  const headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0]
                    .map(function (h) { return String(h).trim().toLowerCase(); });
  const vCol = headers.indexOf('visitor');
  if (vCol === -1) { Logger.log('visitor 列が見つかりません。'); return; }

  const n    = lastRow - 1;
  const rows = sh.getRange(2, 1, n, sh.getLastColumn()).getValues();
  const cur  = sh.getRange(2, col, n, 1).getValues();
  const out  = [];
  let hit = 0;

  for (let i = 0; i < n; i++) {
    if (wanted[String(rows[i][vCol]).trim()]) { hit++; out.push([true]); }
    else { out.push([cur[i][0]]); }
  }

  sh.getRange(2, col, n, 1).setValues(out);
  Logger.log('走査 %s 行 / visitor 一致 %s 行を除外', n, hit);
}


/**
 * アクセス数の多い visitor ID を一覧表示する。
 * 自分の端末の ID を purgeByVisitorId に渡す前の当たりをつける用。
 */
function listTopVisitors() {
  const sh = getLogSheet_();
  const lastRow = sh.getLastRow();
  if (lastRow < 2) { Logger.log('データ行がありません。'); return; }

  const headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0]
                    .map(function (h) { return String(h).trim().toLowerCase(); });
  const vCol = headers.indexOf('visitor');
  if (vCol === -1) { Logger.log('visitor 列が見つかりません。'); return; }

  const rows = sh.getRange(2, 1, lastRow - 1, sh.getLastColumn()).getValues();
  const count = {};
  rows.forEach(function (r) {
    const v = String(r[vCol] || '').trim();
    if (v) count[v] = (count[v] || 0) + 1;
  });

  Object.keys(count)
    .sort(function (a, b) { return count[b] - count[a]; })
    .slice(0, 30)
    .forEach(function (v) { Logger.log('%s\t%s 件', v, count[v]); });
}


/* ============================================================
 *  集計側で使うヘルパー
 * ============================================================ */

/**
 * 集計時に除外行を弾くための判定。
 * ダッシュボードの集計ループに次のように差し込む：
 *
 *     rows.forEach(function (r) {
 *       if (isExcludedRow_(r, idx)) return;   // ← これを追加
 *       …既存の集計…
 *     });
 *
 * idx は getColumnIndex_(sheet) で一度だけ作っておく。
 *
 * @param {Array} row シートの 1 行分の配列
 * @param {Object} idx getColumnIndex_ が返すヘッダー→列番号のマップ
 * @return {boolean} true なら集計から除外
 */
function isExcludedRow_(row, idx) {
  if (idx && idx[EXCLUDED_HEADER] !== undefined) {
    if (row[idx[EXCLUDED_HEADER]] === true) return true;
  }
  // excluded 列がまだ無い / 未処理の行に備えて UA・host でも判定する
  if (idx && idx.ua !== undefined && BLOCK_UA.test(String(row[idx.ua] || ''))) return true;
  if (idx && idx.host !== undefined && BLOCK_HOST.test(String(row[idx.host] || ''))) return true;
  return false;
}


/** ヘッダー名（小文字）→ 0 始まりの列インデックス のマップを返す。 */
function getColumnIndex_(sh) {
  const headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
  const idx = {};
  headers.forEach(function (h, i) { idx[String(h).trim().toLowerCase()] = i; });
  return idx;
}


/* ============================================================
 *  内部ユーティリティ
 * ============================================================ */

/** ログシートを返す。 */
function getLogSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(LOG_SHEET_NAME);
  if (!sh) {
    throw new Error('シート "' + LOG_SHEET_NAME + '" が見つかりません。'
                  + 'LOG_SHEET_NAME を実際のシート名に修正してください。'
                  + '（現在のシート: ' + ss.getSheets().map(function (s) { return s.getName(); }).join(', ') + '）');
  }
  return sh;
}

/**
 * excluded 列が無ければ末尾に追加し、その 1 始まりの列番号を返す。
 * すでにあれば既存の列番号をそのまま返す（列を重複させない）。
 */
function ensureExcludedColumn_(sh) {
  const lastCol = sh.getLastColumn();
  const headers = sh.getRange(1, 1, 1, lastCol).getValues()[0]
                    .map(function (h) { return String(h).trim().toLowerCase(); });
  const found = headers.indexOf(EXCLUDED_HEADER);
  if (found !== -1) return found + 1;

  const col = lastCol + 1;
  sh.getRange(1, col).setValue(EXCLUDED_HEADER);
  return col;
}

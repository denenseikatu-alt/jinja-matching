# 全サイト紹介の長尺動画（1〜2時間）の計画（2026-10-13 オーナー依頼）

急がない依頼。トークンや YouTube の1日の操作の枠、Gemini の回数に余裕を持って、数日に分けて作る。

## オーナーの指定

- 語り手は、記事動画（研究の解説）の女性キャラクター。**画面の中央に全身**で置き、**表情を豊かに**、動きの変化をもっと増やす
- 声は Gemini（Leda・gemini-3.8-flash-lite-tts）。最初から最後まで**同じ声**でそろえる
- 10/17 オーナー指示: 声は**もっと若い女性**に。Gemini は Leda のまま、読み方の指示（style）を「20歳前後の明るく軽い声」に変えた。
  Gemini が使えないときの VOICEVOX は、この動画だけ 雨晴はう（話者10）＋声の高さ +0.03（台本の voice の fallback_speaker / fallback_pitch）
- 動画の始めに自己紹介する。名前は**凛（りん）**（2026年上半期の名づけランキング1位・リクスタ。オーナーが選択）
- 1時間〜2時間。オーナーの全サイトを紹介する

## 紹介するサイト（14）

| サイト | アドレス |
|---|---|
| 田園生活｜健康・フィットネス | https://denenseikatu.com |
| こがね栽培｜NISA・投資入門 | https://koganesaibai.com |
| 縁結びナビ｜婚活アプリ比較 | https://enmusubi-navi.net |
| BIZ-x Ai｜企業のAI導入支援 | https://biz-xai.com |
| ツール農園｜無料お役立ちツール | https://tool-nouen.com |
| 縁結びの導き（数秘術・相性診断） | https://uranai-portal.pages.dev |
| 魂の履歴 | https://tamashii-rireki.pages.dev |
| ASTRA LUMINA | https://astra-lumina.pages.dev |
| 宿曜命式 | https://sukuyo-meishiki.pages.dev |
| 神社マッチング | https://denenseikatu-alt.github.io/jinja-matching/ |
| 反撃の作法 | https://revenge-navi.pages.dev |
| 田園生活ショップ（BASE） | https://denenseikatu.base.shop |
| テンプレート工房（STORES） | https://u5btoqwywc8ql2lhulvn.stores.jp |
| note｜田園生活 | https://note.com/tasty_azalea7101 |

**読み取りの問題（10/13 時点）**: クラウドの作業場所から開けるのは denenseikatu.com だけ。ほかの13サイトは
ネットワークの設定で止められている（ウェブ検索にもまだ出ない）。中身を確かめずに紹介文を作ると事実と違う紹介になるため、
オーナーがクラウドの環境の「許可するドメイン」に13サイトを足すまで、ほかの部分を先に進める。

## オーナーの決定（10/13）

- オンラインコーチング（メッセージでの相談）は**無料**として紹介する。有料は都内の出張コーチング（1時間8,000円）だけ
- uranai-portal.pages.dev は「**縁結びの導き**」の名前で紹介する
- テンプレート工房（STORES）は**名前とアドレスだけ**を短く紹介する（サイトが確認画面で読めないため。中身は言わない）

## 作り方

1. **台本**（1サイト約5〜7分＋自己紹介・締め＝約1時間半、読み上げ約3万字）
   - 各サイトを実際に開いて、目的・主な中身・使い方・どんな人に向くかを確かめてから書く。サイトにないことは言わない
   - 占い・婚活・投資・AI導入のサイトは、効果や儲けを言い切らない（投資は元本割れの可能性、占いは楽しみ方として紹介）
2. **語り手の絵**（Gemini の画像生成 → isnet-anime で切り抜き）
   - 同じ人物の全身・正面・中央立ちを基本に、ポーズ（お辞儀・手を振る・左右の資料を示す・指さす・拍手・考える・
     親指・両手で説明・歩き出す・振り向くなど）と表情（笑顔・満面の笑み・驚き・ひらめき・ウインク・照れ・真剣など）を
     それぞれ作る（合わせて20〜30枚）。まず数枚で人物がそろうかを試し、オーナーに見てもらってから全部作る
3. **画面の構成**: 語り手を中央に全身で置き、左にサイト名とアドレスのカード、右に要点のカード。
   ポーズと表情は文の内容（紹介・驚き・注意など）とランダムを組み合わせて切り替え、体の揺れ・呼吸・首の動きも続ける
4. **声**: 全編を同じ voice（Leda）・同じ style の文・同じモデルで作り、照合（tts_gemini.verify）で合わない文は作り直す
5. **書き出しとアップロード**: 書き出しは動画の長さの約2倍（約3時間）。日本時間16時以降にアップロードする
   （1本で操作の枠を1,600使う。毎朝の3本の分を残す）

## 進み具合

- 10/15 語り手の絵: 全身・画面中央の凛を25枚作った（`assets_video/poses_rin/`、一覧は `docs/youtube/rin_test/rin_all_sheet.jpg`）。
  作り方は `python3 make_poses_gemini.py <名前> "<ポーズ>" --full --src assets_video/poses_rin/smile.png -o assets_video/poses_rin`
  （笑顔の絵を元にすると人物がそろう）。オーナー確認済み（「その方向でいいです」）。
  全身だと顔が小さいので、驚き・笑いなどの場面だけ顔に寄せる（拡大する）
- 次: 12サイトを読んで `pr_sites_notes.md` を埋める → 台本 → 切り抜き（isnet-anime）と口の動き → 書き出し
- 10/16 オーナー指示で構図を変更: 全身ではなく**記事動画と同じ大きさ（腰から上）**。凛は**画面の右**に立ち、左にスクリーン。
  背景は3案（スタジオ・書斎・温室のテラス）からオーナーが **C 温室のテラス** を選んだ。
  絵は `assets_video/poses_rin_garden/`（base と20ポーズ。一覧 `docs/youtube/rin_test/rin_garden_sheet.jpg`）。
  作り方: `python3 make_poses_gemini.py <名前> "<ポーズ>" --same --src assets_video/poses_rin_garden/base.png -o assets_video/poses_rin_garden`
  全身の絵（`assets_video/poses_rin/`）は使わない
- 次: 12サイトの下調べ（10/17）→ 台本 → 切り抜き（isnet-anime）・口とまぶたの位置・スクリーンの位置の設定 → 書き出し
- 10/16 訂正: オーナーが選んだのは **B 書斎**（温室のテラスではなかった）。`assets_video/poses_rin_library/base.png` を元に
  20ポーズを作り直す（`--same --src assets_video/poses_rin_library/base.png -o assets_video/poses_rin_library`。ポーズの一覧は
  温室の回と同じ）。Gemini の前払いの残高が切れたため、オーナーが残高を足してから作る。温室の絵（poses_rin_garden）は使わない
- 10/16 オーナー指示: 今は Gemini の残高を足せないので、**できているもの（全身の凛の絵 `assets_video/poses_rin_cut/`）を使う**。
  試しの動画 `docs/youtube/rin_test/rin_full_test.mp4`。書き出しは `build_talking.py --presenter assets_video/poses_rin_cut/smile.png
  --layout assets_video/poses_rin_cut/layout.json --poses assets_video/poses_rin_cut/poses.json --room assets_video/poses_rin_cut/room_clean.png`。
  声は Gemini が使えなければ自動で VOICEVOX（波音リツ）になる。BGM は雑学と同じ Escort（`--bgm`）
- 10/17 下調べ: 12サイトを読んで `pr_sites_notes.md` を埋めた（STORES は STORES 側の守りで読めず、ほかのサイトの案内からわかる範囲だけ）。
  台本で言い切らない点は同じファイルの「2. 台本の前に知っておくこと」にまとめた。
- 次: 台本（約3万字）→ 口とまぶたの位置などの設定 → 書き出し → 日本時間16時以降にアップロード
- 10/17 台本: `talk/all-sites-tour.json`（93場面・読み上げ約19,500字。読み上げの速さを1分あたり約330字とみて約1時間）。
  構成は 自己紹介 → 体づくり（田園生活・ショップ・note）→ お金と仕事（こがね栽培・ツール農園・biz xAI・反撃の作法）→
  ご縁（縁結びナビ・神社マッチング）→ 占い4サイト → 別冊の売り場（STORES）→ 目的別の回り方・締め。
  読み上げの文に英字は入れず、カタカナの読みを `caption_replace` で字幕だけ元の表記に戻す。中身は `pr_sites_notes.md` に書いたことだけ。
  オーナーに確かめること: 運営者の経歴は「トレーニング歴約40年」で読んでいる（BASE の「指導歴」とは言わない）／STORES の店名「テンプレート工房」と品ぞろえ／
  2時間に近づけたい場合は、各サイトの記事やツールの実演を足して伸ばす
- 10/17 オーナー指示で田園生活を厚くした: 研究ノートの記事20本の読み解き、無料アプリ8つの取り扱い説明（画面の項目どおりの手順）、
  メルマガ・教材の中身を追加。台本は148場面・約36,500字（うち田園生活 約19,700字）で、全体で約2時間の見込み。
  経歴は「トレーニング歴約40年」でよい（オーナー確認済み）。箇条書きの長い場面（教材の中身など）は、書き出しの試しでスクリーンからはみ出さないか確かめる
- 10/20 オーナー決定: 声は **Gemini の Leda**（試し `docs/youtube/rin_test/voice_sample_2026-10-20_gemini.mp3` で確認）。
  本番の書き出し（out_alltour/・約4時間）と、日本時間16時以降の公開を、毎朝の動画のセッションに依頼した（10/20 3時2分から）
- 10/20 本番前の確認: 148場面のうち111場面でスライドの箇条書きが下で切れ、148文で字幕が3行以上になって切れていた。
  `build_talking.py` を直した（入りきらないスライドは文字を少しずつ小さくして収める・長い字幕は読点で2行以内に分けて順に出す・
  字幕の置き換えは長い語から1回だけ（「研究ノート」が「研究note」にならない）・`--no-fallback` で Gemini が使えないとき止める）。
  本番の書き出しは 10/20 3時13分に開始（out_alltour/、ログ /tmp/claude-0/alltour.log）
- 10/20 5時37分: Gemini の音声生成に**1日100回の上限**（gemini-3.8-flash-lite-tts・モデルごと・日本時間16時に戻る）があり、
  780文のうち266文で止まった（ほかに、通信切れ・文字起こしの返事の形・アドレスの文の照合で止まり、それぞれ直した）。
  16時2分から続きを作る。残り約514文で、作り直しを含めて約60回の見込み。毎朝の動画（記事・雑学）も同じ枠を使うので、
  1日に両方は入りきらない
- 10/20 オーナー了承: 毎朝の動画は、lite の1日100回を使い切ったら同じ Leda の声のまま `gemini-3.8-flash-tts`（別に1日100回）に切り替える
  （`cloud/unlock.sh` の GEMINI_TTS_MODEL を2つ並べた）。全サイト紹介動画は声をそろえるため、
  コマンドの前に `GEMINI_TTS_MODEL=gemini-3.8-flash-lite-tts` を付けて lite だけで作る

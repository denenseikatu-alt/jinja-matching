# 英語圏向けの観光動画2本を YouTube に上げる（2026-11-07 オーナー依頼）

Mac の ~/Movies で動く Claude Code が読んで実行する手順。報告は日本語で短く。鍵や ~/.video_env の中身は表示しない。うまくいかなければ止めて報告する。

## ファイル（~/Movies）
1. 関西編: ep1v2_final.mp4 / ep1_thumb.jpg / ep1v2_upload.txt / ep1v2.srt
2. 新潟編: ep2v2_final.mp4 / ep2_thumb.jpg / ep2v2_upload.txt / ep2v2.srt

## 決まり
- タイトル・説明文・タグは各 *_upload.txt のとおり。説明文は書き換えない。数字や主張を足さない。
- サムネイルと英語字幕を設定し、合成コンテンツ（AI 音声）の申告をオンにする。
- 関西編は今すぐ公開。新潟編は関西編の公開のちょうど2日後（日本時間）に予約公開。

## 手順
1. 4ファイル×2本がそろっているか確かめ、*_upload.txt を表示する。
2. この jinja-matching のクローンで `git fetch origin claude/denen-video-pipeline-myltss` し、
   `git show origin/claude/denen-video-pipeline-myltss:upload_tourism.py > upload_tourism.py` で取り出す。
   `test -f ~/.video_env && echo ある`（中身は見ない）と `python3 -c "import googleapiclient"` を確かめる。無ければ止めて報告。
3. `--apply` なしで2本とも実行し、表示が *_upload.txt と一致するか確かめる。
   `python3 upload_tourism.py --video ~/Movies/ep1v2_final.mp4 --thumb ~/Movies/ep1_thumb.jpg --srt ~/Movies/ep1v2.srt --meta ~/Movies/ep1v2_upload.txt`
4. 一致したら関西編を `--apply` で公開し、終わった時刻を控える。
5. 新潟編を、その2日後の同じ時刻で `--publish-at 2026-11-09T時:分 --apply` にして予約する。
6. 2本の URL と、最後に出る「確認:」の行を報告する。

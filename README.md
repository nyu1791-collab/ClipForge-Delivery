# ClipForge Delivery

Windows PC上で配信者ごとの案件、ClipForgeの制作状況、完成動画・字幕・タイトルと納品記録を扱うローカル用アプリです。ClipForgeは別リポジトリとして利用します。広告やメッセージ、SNS投稿を送信する機能はありません。

## 準備（Windows PowerShell）

Python 3.11以降が必要です。登録済み動画の管理にはClipForgeの接続は不要です。ClipForgeから新しく制作する場合は、GitHub CLI、認証済みのClipForgeとその `.venv` も必要です。ClipForgeはGitHub Actionsを起動し、モデル・GPU・ネットワークや認証が必要です。PC上で完結する推論ではありません。

リポジトリをPCへ取得したら `start-windows.cmd` をダブルクリックして起動できます。初回は仮想環境と依存ライブラリを準備します。利用中は開いた画面を閉じず、表示されたURLをブラウザで開いてください。ClipForgeを隣のフォルダに配置していれば自動で参照します。

PowerShellで手動起動する場合：

```powershell
git clone https://github.com/nyu1791-collab/ClipForge.git
git clone https://github.com/nyu1791-collab/ClipForge-Delivery.git
cd ClipForge-Delivery
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
$env:CLIPFORGE_DIR = (Resolve-Path ..\ClipForge).Path
.\.venv\Scripts\python app.py
```

ブラウザで `http://127.0.0.1:8765` を開きます。別の場所に保存する場合は起動前に `CLIPFORGE_DELIVERY_DATA` を指定します。既定のデータ保存先は `~/.clipforge-delivery`。DBと制作物はGitに含めません。シングルユーザー・ローカル利用向けで、外部公開や複数人の同時利用を想定していません。

## 使い方

案件を登録し、案件画面のボタンで初めて制作を開始します。横型・縦型・両方・CapCut向けの選択に対応します。CapCut向けは制作形式の指定で、CapCutドラフトを自動作成する機能はこの画面にはありません。開始済み案件の重複投入を防ぎ、同一案件では制作コントローラーと再接続を同時に実行しません。保存済みのproduction-stateがある場合は既存Runへの再接続ができます。取得したRun IDと状態を画面に表示します。ステータスは表示時に保存済みの記録から読み、GitHubの現在状態を自動更新するものではありません。中断後は記録が古い場合があるのでGitHubのRunと `controller.log` を確認してください。

案件は配信者名・案件名で検索でき、納品状況で絞れます。配信者名・案件名・納期・メモの修正、動画ごとの納品状況・メモの記録もできます。制作元URLと形式の変更は既存のRunと混同しないよう対応していません。

回収された動画は案件画面で再生でき、動画・SRT・ASSを個別に保存できます。納品用タイトルは画面から変更でき、変更はZIP内の `titles.json` に反映されます。SRT字幕は手動で編集し、`captions-edited.srt` として元字幕と別に保存できます。編集版は選択した動画のZIPにも同梱します。字幕を編集しても、動画に焼き込まれた字幕やASSは変わりません。元の動画、字幕、ClipForgeの制作記録は変更しません。

納品する動画だけを選んでZIPにまとめることもできます。ZIPの作成は配信者への送信ではありません。納品済み・リンク・費用は手入力で記録し、費用の内訳は通貨ごとに合計します。費用概要と内訳は別記録です。API請求情報や残高の自動取得は行いません。素材・字幕は非公開で管理してください。

`ClipForge` のActions、Vertex、Colabの接続は別途必要です。実行が中断・不明となった場合、ログと保存済みRunの状態を確認し、新しい案件から同じ依頼を重複投入しないでください。データのバックアップ・削除はユーザーが管理します。

排他制御はこのバージョンのDeliveryが起動した処理に適用されます。別のターミナルや以前のバージョンから同じ制作を操作する場合は、実行中の処理を確認してください。バックアップするときは、制作・再接続が終わっていることを確認してアプリを終了し、データ保存先フォルダ全体を非公開の場所にコピーしてください。SQLiteのDB、字幕編集版、制作物が含まれます。

## 設計の参考

- [GitHub video-workflow topic](https://github.com/topics/video-workflow): 動画案件を中心に制作工程をまとめる考え方。
- [ClipForge](https://github.com/nyu1791-collab/ClipForge): 保存済みproduction-stateを使う再接続と、素材・字幕を非公開に保存する既存の方式。

上記から設計の考え方を参考にし、このリポジトリのコードは独自に実装しています。

別の場所に保存済みのClipForge完成クリップは、案件画面の「完成動画を取り込む」で `video.mp4` を含むフォルダを指定し、字幕やタイトル記録と一緒にコピーできます。元のファイルは変更しません。


制作の目標・再開・接続の整理は [制作経路の整理](docs/STREAMLINING.md) を参照してください。

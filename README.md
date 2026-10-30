# ClipForge Delivery

Windows PC上で配信者ごとの案件、ClipForgeの制作状況、完成動画・字幕・タイトルと納品記録を扱うローカル用アプリです。ClipForgeは別リポジトリとして利用します。広告やメッセージ、SNS投稿を送信する機能はありません。

## 準備（Windows PowerShell）

Python 3.11以降、GitHub CLI、ClipForgeとその `.venv` が必要です。ClipForgeは現在の実装どおりGitHub Actionsを起動し、モデル・GPU・ネットワークや認証が必要です。PC上で完結する推論ではありません。

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

案件を登録し、案件画面のボタンで初めて制作を開始します。横型・縦型・両方・CapCut向けの選択に対応します。開始済み案件の重複投入は防ぎます。保存済みのproduction-stateがある場合は既存Runへの再接続ができます。取得したRun IDと状態を画面に表示します。ステータスは表示時に保存済みの記録から読み、GitHubの現在状態を自動更新するものではありません。

回収された動画・SRT・ASSとタイトルはZIPにまとめられます。ZIPの作成は配信者への送信ではありません。納品済み・リンク・費用は手入力で記録し、API請求情報や残高の自動取得は行いません。素材・字幕は非公開で管理してください。

`ClipForge` のActions、Vertex、Colabの接続は別途必要です。実行が中断・不明となった場合、ログと保存済みRunの状態を確認し、新しい案件から同じ依頼を重複投入しないでください。データのバックアップ・削除はユーザーが管理します。

## 設計の参考

- [GitHub video-workflow topic](https://github.com/topics/video-workflow): 動画案件を中心に制作工程をまとめる考え方。
- [ClipForge](https://github.com/nyu1791-collab/ClipForge): 保存済みproduction-stateを使う再接続と、素材・字幕を非公開に保存する既存の方式。

上記から設計の考え方を参考にし、このリポジトリのコードは独自に実装しています。

# 完成物を受け取り、納品用にまとめる

Deliveryは制作済みファイルを受け取る管理アプリです。制作は別アプリ側で行い、PCへ回収した完成物を取り込みます。

## ClipForgeの完成物を取り込む

ClipForgeで制作・回収した結果フォルダを用意します。結果をZIPで取得した場合はPC上で展開します。

```text
result/
  manifest.json
  clips/
    clip-001/
      video.mp4
      captions.srt
      captions.ass
      render.json
    clip-002/
      video.mp4
      ...
```

Deliveryの案件画面で「動画をまとめて取り込む」を開き、`result/manifest.json` のパスを指定します。ClipForgeの一覧にある `rendered` 配列の `directory` を、一覧ファイルの場所からの相対パスとして読み取ります。

```json
{
  "rendered": [
    {"directory": "clips/clip-001"},
    {"directory": "clips/clip-002"}
  ]
}
```

一つだけ取り込むときは、「完成動画を取り込む」で `video.mp4` が入ったフォルダを指定します。この受け渡しにGitHubへの接続や、ClipForgeのPython環境の指定は必要ありません。

## 汎用の素材一覧から取り込む

ほかの制作アプリで作った完成物も、同じフォルダ形式にすれば取り込めます。一覧ファイルは次の形式を使えます。

```json
{
  "clips": [
    {
      "directory": "C:/work/clips/clip-001",
      "title": "納品する動画のタイトル",
      "mode": "tiktok-capcut"
    },
    {
      "directory": "C:/work/clips/clip-002",
      "title": "別の動画のタイトル",
      "mode": "tiktok"
    }
  ]
}
```

動画形式は `long`、`tiktok`、`tiktok-capcut` に対応します。相対パスは一覧ファイルのある場所が基準です。フォルダ名だけを並べた形式も使えます。

```json
{
  "clips": [
    "C:/work/clips/clip-001",
    "C:/work/clips/clip-002"
  ]
}
```

形式の記載がない素材は、画面の「形式の記載がない場合」で指定した形式で取り込みます。一覧のタイトルは納品用タイトルに反映され、Deliveryで後から編集したタイトルは再取り込み時も保持します。

## 再取り込みと更新

同じ案件に同じ動画を再指定すると、元動画の保存先・サイズ・更新日時を使って既存のコピーを再利用します。動画は同じで字幕や制作記録だけが更新されていれば、動画を再コピーせず付随ファイルだけを差し替えます。元動画自体が更新された場合は、新しい動画として取り込みます。

素材の一部がまだ存在しない場合も、取り込める残りの動画を続行します。画面には未取込の理由と、取り込んだ本数・再利用した本数・字幕などを更新した本数を表示します。素材がそろった後は、同じ一覧を再指定できます。

## 対応する完成フォルダ

| 元フォルダのファイル | Deliveryでの保存名 |
|---|---|
| `video.mp4` | `video.mp4` |
| `captions.srt` または `subtitles.srt` | `captions.srt` |
| `captions.ass` または `subtitles.ass` | `captions.ass` |
| `render.json`（ある場合） | `render.json` |

両方の字幕名がある場合は `captions.srt`・`captions.ass` を優先します。このため、`subtitles.srt`・`subtitles.ass` という名前で字幕を書き出す制作アプリの完成物も取り込めます。

元のフォルダとファイルはそのまま保管できます。編集用タイムラインや字幕だけから完成MP4を生成する処理は含みません。編集した動画は制作アプリから `video.mp4` として新しいフォルダに書き出し、その完成物を取り込んでください。

## 納品用ZIPを作る

案件画面で動画を選び、「選択した動画をZIPにする」を押します。動画・元字幕・保存済みの字幕編集版と、次の案内ファイルをまとめます。

- `titles.json`：案件名と動画ごとの納品用タイトル・保存先。
- `納品内容.txt`：案件名、配信者名、動画本数、動画タイトルと保存先の一覧。字幕編集版の扱いも記載します。

`captions-edited.srt` はDeliveryで手修正した字幕です。元のSRT・ASSと別に同梱され、動画に焼き込まれた字幕を変更するものではありません。

ZIPを作った後、ユーザーが選んだ方法で納品します。Deliveryは配信者へのメッセージ送信やSNS投稿を行わず、納品状況・リンクを案件に記録します。

## 更新後の起動

`start-windows.cmd` は一括取り込みに使う依存ライブラリも用意します。手動起動する場合は、更新後に次のコマンドで依存をそろえてください。

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

## 取込元の制作記録

素材一覧を指定した場合、取込元の一覧ファイルへの参照を案件内へ保存します。その親フォルダにClipForgeの `production-state.json` があれば、保存済みの状態・Run番号を読み取り専用で表示します。画面を再読み込みするとローカルの保存記録を読み直します。ClipForgeのコードを実行したり、APIでRunを監視・再投入したりしません。制作記録のない完成物もそのまま取り込めます。

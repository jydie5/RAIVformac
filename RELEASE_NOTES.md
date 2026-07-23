# RAIV for mac v0.3.0-alpha

## Highlights

- English and Japanese interface with automatic macOS language detection
- Language selector in the bookshelf header
- English bookshelf, reader controls, dialogs, keyboard help, and processing status
- Faster back-and-forth page navigation with asynchronous display decoding
- Adaptive Real-CUGAN prefetch with bounded forward, backward, memory, and disk caches
- English-first public documentation and freely licensed demo books

The standalone ZIP includes RAIV.app and the pinned Real-CUGAN engine. End users
do not need Python, uv, or a separate AI engine installation.

## 主な変更

- macOSの優先言語に追従する英語／日本語UI
- 本棚右上に言語選択を追加
- 本棚、読書設定、確認画面、ヘルプ、補正状態を英語化
- 非同期画像デコードにより前後ページ移動を高速化
- 前後ページを過不足なく保持する適応型Real-CUGAN先読み
- 英語を基本とした公開ドキュメントと自由ライセンスのデモ本

## Features

- 縦方向に画像が最大化された見開きでも、左右ページを中央の綴じ目へ寄せて表示
- 全画面表示では下部ステータス行を隠し、画像に使える縦方向の表示領域を拡大
- 先読み範囲を前方12ページ・後方4ページへ再配分し、速いページ送りへの余裕を拡大
- 原画・自然・クリーニング・高画質の4種類に整理した「かんたん」画質モード
- モデルやnoiseなどを調整できる「マニュアル」画質モード
- 名前付きカスタム画質設定の保存・読込・上書き・削除
- 読書速度と実測補正時間に応じて前方12〜24ページへ伸縮する適応先読み
- かんたんモードでは先読みの詳細ログを隠し、読書を妨げないバックグラウンド処理へ変更

## Fixes

- 先読み中のページ移動で、見開きの片側だけ補正画像になる問題を修正
- 左右の補正がそろうまで見開き全体を原画で表示し、完成後に同時切り替え
- 古い先読み処理が完了してから現在位置へ追従する際の結果混入を防止
- 補正キャッシュと表示用キャッシュを現在位置周辺へ限定し、無制限なディスク増加を防止
- ウィンドウ終了時にタイマー、イベント監視、縮小画像キャッシュを解放
- 前後移動のたびに先読みを破棄していた処理を廃止し、補正済みページ間の往復を高速化
- 表示画像の予熱とキャッシュ整理を操作停止後へ移し、キー入力中の引っ掛かりを低減
- 補正済みディスクキャッシュを後方12ページまで保持し、短い読み返しでの再補正を防止
- PNG読込、グレースケール変換、高品質縮小を表示スレッドから分離
- 補正版が未予熱でも原画見開きを先に表示し、補正版が左右揃ってから同時に差し替え
- 15〜19MBの実画像でキー応答0.68ms、初回見開き表示15.57msを確認
- 読書位置のSQLite保存を350msデバウンスし、連続ページ送り中の同期書込みを廃止

## Next

今後の設計と実装順は[ROADMAP.md](ROADMAP.md)に記載します。

# RAIV for mac v0.2.0-alpha

一般ユーザーがPythonやターミナル操作なしで試せるstandalone版です。

## 主な変更

- 公式Real-CUGAN 20220728 macOS実行ファイルとモデルを同梱
- 公式ZIPと実行ファイルをSHA256で検証する再現可能なビルド
- Real-CUGAN、モデル、ncnn、libwebp、MoltenVK、LLVM OpenMPのライセンス全文をアプリへ収録
- 原画／補正版チェック切り替え時の表示キャッシュを破棄し、即時再描画
- 比較チェックの表示を`原画を表示（OFFで補正版）`へ明確化
- 一般ユーザー向け日本語READMEとインストールガイド

## ダウンロード

`RAIVformac-v0.2.0-alpha-macos-apple-silicon-standalone.zip`をダウンロードしてください。Python、uv、Real-CUGANの個別インストールは不要です。

## 初回起動

このα版は署名・Apple notarization未実施です。ZIPを展開して`RAIV.app`をアプリケーションへ移動し、初回だけControlキーを押しながらクリックして`開く`を選んでください。

## 対象環境

- Apple Silicon Mac
- macOS 13以降を推奨

## ライセンス

RAIV for mac本体はMIT Licenseです。同梱物の由来とライセンスは`THIRD_PARTY_NOTICES.md`およびアプリ内の`Contents/Resources/licenses/`を参照してください。

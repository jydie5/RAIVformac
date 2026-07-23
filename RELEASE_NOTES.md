# Unreleased

## Features

- 縦方向に画像が最大化された見開きでも、左右ページを中央の綴じ目へ寄せて表示
- 全画面表示では下部ステータス行を隠し、画像に使える縦方向の表示領域を拡大
- 先読み範囲を前方12ページ・後方4ページへ再配分し、速いページ送りへの余裕を拡大

## Fixes

- 先読み中のページ移動で、見開きの片側だけ補正画像になる問題を修正
- 左右の補正がそろうまで見開き全体を原画で表示し、完成後に同時切り替え
- 古い先読み処理が完了してから現在位置へ追従する際の結果混入を防止
- 補正キャッシュと表示用キャッシュを現在位置周辺へ限定し、無制限なディスク増加を防止
- ウィンドウ終了時にタイマー、イベント監視、縮小画像キャッシュを解放

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

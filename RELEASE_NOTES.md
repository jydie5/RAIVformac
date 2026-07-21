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

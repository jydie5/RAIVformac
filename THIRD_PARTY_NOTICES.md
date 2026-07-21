# Third-Party Notices

RAIV for macのstandalone版は、以下の公式macOSパッケージを同梱します。

## Real-CUGAN ncnn Vulkan

- Project: [nihui/realcugan-ncnn-vulkan](https://github.com/nihui/realcugan-ncnn-vulkan)
- Release: [20220728 macOS](https://github.com/nihui/realcugan-ncnn-vulkan/releases/tag/20220728)
- Archive: `realcugan-ncnn-vulkan-20220728-macos.zip`
- Archive SHA256: `0df908cbb98b480f85897221b96d37b0bdb70f82d81b2c7037fe950dd5c0fa33`
- Executable SHA256: `a59aa9acd89115e33d7d71d7e413b405237833f331bdc87d4e20099af0e5e819`
- License: MIT
- Copyright: Copyright (c) 2019 nihui

実行ファイルとモデルは公式リリースZIPから取得し、内容を改変せずアプリへ収録します。ビルドスクリプトはダウンロードしたZIPと実行ファイルのSHA256を照合します。

## Real-CUGAN models

- Project: [bilibili/ailab Real-CUGAN](https://github.com/bilibili/ailab/tree/main/Real-CUGAN)
- License: MIT
- Copyright: Copyright (c) 2022 bilibili

公式`realcugan-ncnn-vulkan`リポジトリと20220728リリースZIPには、`models-se`、`models-pro`、`models-nose`のモデルが含まれています。

## Statically linked dependencies

公式macOS実行ファイルのビルド定義に基づき、次のライセンス全文もstandaloneアプリへ収録します。

- [Tencent ncnn](https://github.com/Tencent/ncnn): BSD 3-Clauseおよび同梱第三者ライセンス
- [libwebp](https://github.com/webmproject/libwebp): BSD 3-Clause、追加特許許諾
- [MoltenVK v1.1.1](https://github.com/KhronosGroup/MoltenVK/releases/tag/v1.1.1): Apache License 2.0
- [LLVM OpenMP 11.0.0](https://github.com/llvm/llvm-project/tree/llvmorg-11.0.0/openmp): Apache License 2.0 with LLVM Exceptions

ライセンス全文は`RAIV.app/Contents/Resources/licenses/`へ収録されます。PyInstallerのmacOSバンドル構造によっては、同じ場所へのシンボリックリンクが`Contents/Frameworks`側にも作られます。

## Python runtime and libraries

standalone版はPythonランタイム、PySide6/Qt、Pillow、py7zr、rarfileと、それらが利用するライブラリを同梱します。ビルド時にインストール済みパッケージのライセンスファイルを収集し、すべて`RAIV.app/Contents/Resources/licenses/`へ収録します。

- Python: Python Software Foundation License
- PyInstaller bootloader/runtime: GPL 2.0 or later with the PyInstaller Bootloader Exception
- PySide6 / Qt: LGPL v3（または各プロジェクトが提示する選択ライセンス）
- Pillow: MIT-CMU
- py7zrおよび一部の圧縮ライブラリ: LGPL 2.1 or later
- rarfile: ISC
- setuptoolsおよびpackaging: MIT、Apache 2.0またはBSD系ライセンス

PySide6/Qtの正確なバージョン、対応ソース、動的リンクされたQtライブラリの場所と差し替え後の再署名方法は、アプリ内の`Qt-PySide6-source-and-relinking.txt`に記載します。Pillowが同梱する画像形式ライブラリなどの第三者表示は、Pillowのライセンスファイルに含まれます。

## RAIV relationship

RAIV for macは[nalltama/RAIV](https://github.com/nalltama/RAIV)に着想を得た独立実装です。本家RAIVのコードをコピーしたforkではなく、本家の公式リリースでもありません。

この文書は同梱物の由来とライセンス表示を記録するもので、法的助言ではありません。

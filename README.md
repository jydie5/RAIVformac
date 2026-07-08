# RAIV for mac

RAIV for mac is an independent macOS / Apple Silicon manga and image archive viewer inspired by [nalltama/RAIV](https://github.com/nalltama/RAIV).

This project is not an official RAIV release.

## Download

Download the latest build from:

https://github.com/jydie5/RAIVformac/releases

For the first alpha release, download:

```text
RAIVformac-v0.1.0-alpha-macos-arm64-unsigned.zip
```

## Install

1. Download and unzip the release file.
2. Move `RAIV.app` to `Applications` or any folder you prefer.
3. On first launch, right-click `RAIV.app` and choose `Open`.
4. If macOS shows a security warning, choose `Open`.

This alpha build is unsigned and not notarized, so a normal double-click launch may be blocked by macOS on first launch.

## Features

- Bookshelf-style library
- Drag and drop import
- Local image folders and image archives
- `zip`, `cbz`, `rar`, `cbr`, `7z`, and `cb7` support
- Cover grid
- Right-bound manga spread reading
- Keyboard navigation
- One-page spread alignment adjustment
- Reading progress overlay
- Optional local AI correction path using a user-provided Real-CUGAN executable

## Local Library

Imported books are stored under:

```text
~/RAIV Library
```

Original archive files are not deleted when importing into RAIV for mac.

AI correction cache files are stored under macOS cache folders and can be regenerated.

## AI Correction

The public alpha does not bundle Real-CUGAN binaries or model weights.

Reasons:

- third-party redistribution terms must be handled carefully
- the app should remain usable as a normal viewer
- users should not receive unexpected executable model files in an unsigned alpha

Advanced users can point the app to a local Real-CUGAN executable:

```bash
export RAIV_REALCUGAN_PATH=/path/to/realcugan-ncnn-vulkan
open /Applications/RAIV.app
```

The app works without this engine; AI correction is optional.

## Keyboard Shortcuts

For right-bound manga:

- `Left` / `Space`: next spread
- `Right`: previous spread
- `Shift + Left`: move forward one page
- `Shift + Right`: move back one page
- `F`: fullscreen
- `P`: settings panel
- `?`: help
- `Esc`: exit fullscreen or return to bookshelf

## Current Status

This is an early alpha for human testing.

Known limitations:

- unsigned and not notarized
- AI engine path setup is still manual
- UI is still being refined
- release builds currently target Apple Silicon macOS

## Acknowledgements

RAIV for mac is inspired by [nalltama/RAIV](https://github.com/nalltama/RAIV), which explores high-quality local image viewing with Real-CUGAN / Real-ESRGAN based upscaling.

This macOS project is an independent implementation and is not an official RAIV release.

## Developer Notes

End users do not need Python, uv, or any development tools.

For developers who want to build from source:

```bash
uv sync
uv run --extra app python scripts/build_macos_app.py
```

The local app bundle is created at:

```text
dist/RAIV.app
```

Development tests and benchmark fixtures are not included in the public alpha branch until they are replaced with redistributable synthetic sample data.

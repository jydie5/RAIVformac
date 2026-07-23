# RAIV for mac

[English](README.md) | [日本語](README.ja.md)

RAIV for mac is a free, open-source macOS comic reader and image viewer for
Apple Silicon. It reads CBZ, CBR, ZIP, RAR, 7z, image folders, and individual
images, combining a visual bookshelf, two-page manga reading, and automatic
Real-CUGAN AI upscaling in a native desktop application.

This is an independent macOS implementation inspired by
[nalltama/RAIV](https://github.com/nalltama/RAIV). It is not an official release
of the original RAIV project.

![RAIV bookshelf with freely licensed sample comics](docs/images/bookshelf.png)

![RAIV two-page reader with the settings panel open](docs/images/reader.png)

The screenshots use *Pepper&Carrot* by David Revoy under
[CC BY 4.0](demo/ATTRIBUTION.md). No commercial manga pages are included.

## Download

The standalone build does not require Python, uv, or Terminal.

1. Open [Releases](https://github.com/jydie5/RAIVformac/releases).
2. Download the latest file whose name ends in `macos-apple-silicon-standalone.zip`.
3. Unzip it and move `RAIV.app` to Applications.
4. On first launch, Control-click `RAIV.app` and choose **Open**.

The current alpha is not signed or notarized. See
[INSTALL.md](INSTALL.md) for detailed installation and troubleshooting steps.

## Read your first book

1. Launch RAIV to open the bookshelf.
2. Drag a ZIP, CBZ, RAR, CBR, 7z, CB7, image folder, or image onto the window.
3. Confirm the import.
4. Double-click the cover.
5. Press Left Arrow or Space to advance in the default right-bound mode.

RAIV keeps the source archive untouched. It stores an extracted reading copy in
`~/RAIV Library`.

## Features

- Cover-based bookshelf with multi-file drag and drop
- ZIP/CBZ, RAR/CBR, 7z/CB7, image folders, and individual images
- Right-bound manga layout with a single cover and two-page spreads
- Natural title and volume ordering
- Continue to the next volume without leaving full screen
- Reading-position persistence
- Full-screen reading with a translucent progress overlay
- Automatic Real-CUGAN enhancement around the current reading position
- Adaptive forward prefetch and a revolving backward cache
- Non-blocking image decoding with immediate original-image fallback
- Simple quality modes and saved manual presets
- Instant original/enhanced comparison
- Managed library removal without deleting the source archive
- English and Japanese UI with macOS language detection

See [ROADMAP.md](ROADMAP.md) for planned work and known improvement areas.

## Language

RAIV follows the first preferred language in macOS. English and Japanese are
included. Use the **Language** selector in the bookshelf header to choose
**System**, **English**, or **Japanese**. Restart RAIV after changing it so the
bookshelf, reader, dialogs, help, and status messages all use the same language.

## AI enhancement

The standalone package bundles the official
`realcugan-ncnn-vulkan 20220728 macOS` executable and models. It uses the Apple
Silicon GPU through Vulkan/Metal and needs no additional engine setup.

RAIV automatically processes the visible spread and nearby pages in the
background. The cache revolves as you read: normally 12-24 pages ahead and four
pages behind are retained. Original pages remain available immediately while
enhancement catches up.

Press `P` to open Reading Settings. Enable **Show original** to view the source
page; disable it to return to the enhanced page. Pages at or above the default
2234-pixel height threshold are left unchanged.

### Quality modes

| Mode | Purpose |
|---|---|
| Original | Display the source image without enhancement |
| Natural | Balance line clarity and screentone preservation |
| Cleaning | More strongly reduce scan and compression artifacts |
| High quality | Prioritize output quality over processing time |

Manual mode exposes model, scale, noise, tile size, TTA, and the resolution
threshold. Custom combinations can be named and reused.

## Keyboard controls

These are the defaults for right-bound manga.

| Key | Action |
|---|---|
| `Left` / `Space` | Next spread |
| `Right` | Previous spread |
| `Shift + Left` | Shift one page forward |
| `Shift + Right` | Shift one page backward |
| `F` | Toggle full screen |
| `P` | Show or hide Reading Settings |
| `?` | Show keyboard help |
| `Esc` | Leave full screen or return to the bookshelf |

## Free demo books

The [`demo`](demo) directory contains three small ZIP files that can be dropped
directly onto the bookshelf. They contain the English low-resolution exports of
the first three *Pepper&Carrot* episodes. Art and story are by David Revoy, and
the files are redistributed under CC BY 4.0 with attribution included both
beside and inside every archive.

## Storage and removal

- Managed reading copies: `~/RAIV Library`
- AI enhancement cache: `~/Library/Caches/RAIV`
- Database and settings: the RAIV directory in macOS Application Support

Removing a book from the bookshelf deletes RAIV's managed reading copy and
reading state. It never deletes the original ZIP or RAR. To uninstall the app,
remove `RAIV.app`; remove the locations above only if you also want to erase the
bookshelf and cache.

## Current limitations

- Apple Silicon only; Intel Macs are not currently supported.
- The alpha is unsigned and not notarized.
- Some RAR variants may not be compatible with the available macOS extraction
  backend.
- Updates are manual; download a newer build from Releases.

## Build from source

```bash
git clone https://github.com/jydie5/RAIVformac.git
cd RAIVformac
uv sync --extra gui
uv run raiv-viewer
```

Build a local standalone application:

```bash
uv sync --extra app
uv run --extra app python scripts/build_macos_app.py --bundle-engine
```

The build script downloads the official Real-CUGAN macOS archive, verifies its
SHA-256 digest, and bundles it. Unknown local binaries are not substituted.

Run the development test suite:

```bash
uv sync --extra dev
uv run pytest
```

## Support development

RAIV for mac remains free software under the MIT License whether or not you
support its development. Stars, bug reports, testing, and code contributions are
valuable. Optional donations are also compatible with the project licenses, but
no official payment account is configured yet. Trust only funding links
published in this repository.

## License

RAIV for mac is licensed under the [MIT License](LICENSE). Real-CUGAN and other
bundled dependencies are documented in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Demo artwork has its own
[CC BY 4.0 attribution](demo/ATTRIBUTION.md) and is not covered by the MIT
license.

# RAIV for mac v0.1.0-alpha

Initial public alpha for macOS / Apple Silicon.

## Highlights

- Bookshelf import for image folders and common comic archive formats
- Local library extraction under `~/RAIV Library`
- Cover grid bookshelf with reading progress
- Right-bound manga spread viewer
- Keyboard navigation and one-page spread adjustment
- Reading progress overlay
- Optional user-provided Real-CUGAN correction path
- Revolving correction cache around the current spread
- Single-window bookshelf and reader flow

## Distribution Notes

This build is unsigned and not notarized. On first launch, macOS may block a normal double-click launch. Use right-click > Open, then choose Open in the macOS security dialog.

This public alpha does not bundle Real-CUGAN binaries or model weights. AI correction requires a local engine path such as:

```bash
export RAIV_REALCUGAN_PATH=/path/to/realcugan-ncnn-vulkan
```

## Acknowledgement

RAIV for mac is inspired by [nalltama/RAIV](https://github.com/nalltama/RAIV). This is an independent macOS implementation and is not an official RAIV release.

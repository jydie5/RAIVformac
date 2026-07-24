# Hardware compatibility

## Current standalone build

RAIV for mac is distributed as an Apple Silicon `arm64` application. The
bundled Real-CUGAN executable is also native `arm64` and links to Apple's Metal
framework. Intel Macs are not supported by the current standalone package.

The current build targets macOS 11 or later at the binary level. macOS 13 or
later remains the supported recommendation for the complete application.

## MacBook Neo with A18 Pro

Status: **expected to run, physical-device validation pending**.

Apple's MacBook Neo uses an A18 Pro with a six-core CPU, five-core GPU, 16-core
Neural Engine, and 8 GB of unified memory. Apple lists A18-series GPUs as
supporting Metal 3 and Metal 4. These facts match RAIV's `arm64` application and
Metal-backed Real-CUGAN engine, so there is no known instruction-set or graphics
API blocker.

This compatibility conclusion does not imply M4 Pro-level performance.
Real-CUGAN uses the GPU through Metal; it does not currently use the Neural
Engine. The smaller GPU and 8 GB memory ceiling may cause the enhancement cache
to fill more slowly during rapid page turns. The MacBook Neo display is
2408-by-1506, which reduces output workload relative to the project's
3456-by-2234 M4 Pro target.

Official references:

- [MacBook Neo technical specifications](https://support.apple.com/en-us/126322)
- [Apple Metal feature set tables](https://developer.apple.com/metal/capabilities/)
- [Porting macOS apps to Apple silicon](https://developer.apple.com/documentation/Apple-Silicon/porting-your-macos-apps-to-apple-silicon)

## Physical-device acceptance test

Before marking MacBook Neo as verified:

1. Install and open the unsigned standalone package through Privacy & Security.
2. Import ZIP, RAR, and image-folder samples without using copyrighted files.
3. Confirm that the visible spread reaches the enhanced state.
4. Toggle the original/enhanced comparison and verify both pages change.
5. Turn ten spreads forward, then alternate forward and backward navigation.
6. Return more than six pages and confirm enhancement is restored on demand.
7. Observe memory pressure and confirm the app remains responsive during
   background prefetch.
8. Record first-page latency, average enhancement time, and any fallback errors.

from __future__ import annotations

import argparse
import importlib.metadata
import plistlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from fetch_realcugan import ensure_realcugan, fetch_license_files, write_provenance


ROOT_DIR = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT_DIR / "src" / "raiv_app" / "main.py"
DIST_APP = ROOT_DIR / "dist" / "RAIV.app"
APP_ICON_SOURCE = ROOT_DIR / "assets" / "raiv-app-icon.png"
APP_ICON = ROOT_DIR / "build" / "RAIV.icns"
BUNDLE_IDENTIFIER = "jp.raiv.viewer"
APP_VERSION = "0.3.0"
LICENSES_DIR = ROOT_DIR / "build" / "licenses"
RUNTIME_DISTRIBUTIONS = (
    "PyInstaller",
    "setuptools",
    "packaging",
    "Pillow",
    "py7zr",
    "backports-zstd",
    "brotli",
    "inflate64",
    "multivolumefile",
    "psutil",
    "pybcj",
    "pycryptodomex",
    "pyppmd",
    "texttable",
    "rarfile",
)

ICONSET_FILES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def build_app_icon() -> Path:
    if not APP_ICON_SOURCE.is_file():
        raise RuntimeError(f"app icon source was not found: {APP_ICON_SOURCE}")
    iconset_dir = ROOT_DIR / "build" / "RAIV.iconset"
    iconset_dir.mkdir(parents=True, exist_ok=True)
    for filename, size in ICONSET_FILES.items():
        subprocess.run(
            [
                "sips",
                "-z",
                str(size),
                str(size),
                str(APP_ICON_SOURCE),
                "--out",
                str(iconset_dir / filename),
            ],
            check=True,
            capture_output=True,
        )
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(APP_ICON)],
        check=True,
    )
    return APP_ICON


def copy_runtime_license_files(destination: Path) -> int:
    copied = 0
    for package_name in RUNTIME_DISTRIBUTIONS:
        distribution = importlib.metadata.distribution(package_name)
        license_paths = [
            path
            for path in distribution.files or []
            if any(part in Path(path).name.lower() for part in ("license", "copying", "notice"))
        ]
        if not license_paths:
            raise RuntimeError(f"no license file found for runtime dependency: {package_name}")
        for index, relative_path in enumerate(license_paths, start=1):
            source = Path(distribution.locate_file(relative_path))
            suffix = "" if len(license_paths) == 1 else f"-{index}"
            filename = f"Python-{package_name}-{distribution.version}{suffix}-{source.name}"
            shutil.copy2(source, destination / filename)
            copied += 1

    python_license = Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError(f"Python runtime license was not found: {python_license}")
    shutil.copy2(python_license, destination / f"Python-{platform.python_version()}-LICENSE.txt")
    return copied + 1


def write_qt_source_notice(destination: Path) -> None:
    pyside_version = importlib.metadata.version("PySide6")
    notice = destination / "Qt-PySide6-source-and-relinking.txt"
    notice.write_text(
        "RAIV for mac uses PySide6 and Qt under the LGPL v3 option.\n\n"
        f"Bundled PySide6 version: {pyside_version}\n"
        f"PySide6 source: https://github.com/qtproject/pyside-pyside-setup/tree/v{pyside_version}\n"
        f"Qt source: https://github.com/qt/qtbase/tree/v{pyside_version}\n"
        "RAIV application source: https://github.com/jydie5/RAIVformac\n\n"
        "The dynamically linked Qt frameworks are stored below:\n"
        "RAIV.app/Contents/Frameworks/PySide6/Qt/lib/\n\n"
        "You may replace compatible Qt/PySide6 libraries for relinking and then apply your own\n"
        "ad-hoc signature with: codesign --force --deep --sign - RAIV.app\n"
        "The complete LGPL v3 text is included as Qt-PySide6-LGPL-3.0-only.txt.\n",
        encoding="utf-8",
    )


def prepare_license_files(engine_dir: Path | None) -> Path | None:
    shutil.rmtree(LICENSES_DIR, ignore_errors=True)
    LICENSES_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    project_license = ROOT_DIR / "LICENSE"
    if project_license.exists():
        shutil.copy2(project_license, LICENSES_DIR / "RAIV-MIT.txt")
        copied += 1
    third_party_notices = ROOT_DIR / "THIRD_PARTY_NOTICES.md"
    if third_party_notices.exists():
        shutil.copy2(third_party_notices, LICENSES_DIR / "THIRD_PARTY_NOTICES.md")
        copied += 1
    copied += copy_runtime_license_files(LICENSES_DIR)
    copied += len(fetch_license_files(LICENSES_DIR))
    write_qt_source_notice(LICENSES_DIR)
    copied += 1
    if engine_dir is not None:
        shutil.copy2(engine_dir / "LICENSE", LICENSES_DIR / "realcugan-ncnn-vulkan-MIT.txt")
        shutil.copy2(engine_dir / "README.md", LICENSES_DIR / "realcugan-ncnn-vulkan-README.md")
        copied += 2
        write_provenance(LICENSES_DIR, engine_dir)
        copied += 1
    notice = LICENSES_DIR / "README.txt"
    notice.write_text(
        "RAIV third-party notices.\n\n"
        "Standalone builds bundle the pinned official realcugan-ncnn-vulkan macOS package.\n"
        "Keep every file in this directory with redistributed app bundles.\n"
        "Without a bundled engine, set RAIV_REALCUGAN_PATH to a local realcugan-ncnn-vulkan executable.\n",
        encoding="utf-8",
    )
    copied += 1
    return LICENSES_DIR if copied else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a local RAIV.app bundle.")
    parser.add_argument(
        "--bundle-engine",
        action="store_true",
        help="download, verify, and bundle the pinned official Real-CUGAN macOS package",
    )
    return parser.parse_args()


def set_bundle_version() -> None:
    info_path = DIST_APP / "Contents" / "Info.plist"
    with info_path.open("rb") as file:
        info = plistlib.load(file)
    info["CFBundleShortVersionString"] = APP_VERSION
    info["CFBundleVersion"] = APP_VERSION
    with info_path.open("wb") as file:
        plistlib.dump(info, file)
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(DIST_APP)],
        cwd=ROOT_DIR,
        check=True,
    )


def main() -> None:
    args = parse_args()
    if platform.system() != "Darwin":
        raise SystemExit("macOS .app builds must run on macOS.")
    if not ENTRYPOINT.exists():
        raise SystemExit(f"missing entrypoint: {ENTRYPOINT}")
    shutil.rmtree(ROOT_DIR / "build", ignore_errors=True)
    shutil.rmtree(DIST_APP, ignore_errors=True)
    app_icon = build_app_icon()
    engine_dir = ensure_realcugan(ROOT_DIR / "build" / "vendor") if args.bundle_engine else None
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--icon",
        str(app_icon),
        "--name",
        "RAIV",
        "--osx-bundle-identifier",
        BUNDLE_IDENTIFIER,
        "--hidden-import",
        "raiv_app.bookshelf",
        "--hidden-import",
        "raiv_app.library",
        "--hidden-import",
        "raiv_app.page_provider",
        "--hidden-import",
        "PySide6.QtCore",
        "--hidden-import",
        "PySide6.QtGui",
        "--hidden-import",
        "PySide6.QtWidgets",
        "--exclude-module",
        "numpy",
        "--exclude-module",
        "cv2",
        str(ENTRYPOINT),
    ]
    licenses_dir = prepare_license_files(engine_dir)
    if licenses_dir is not None:
        command[4:4] = ["--add-data", f"{licenses_dir}:licenses"]
    if engine_dir is not None:
        command[4:4] = ["--add-data", f"{engine_dir}:engines/{engine_dir.name}"]
    subprocess.run(command, cwd=ROOT_DIR, check=True)
    if not DIST_APP.exists():
        raise SystemExit(f"app build did not create {DIST_APP}")
    set_bundle_version()
    print(f"built: {DIST_APP}")


if __name__ == "__main__":
    main()

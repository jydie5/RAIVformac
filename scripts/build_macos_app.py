from __future__ import annotations

import platform
import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT_DIR / "src" / "raiv_app" / "main.py"
DIST_APP = ROOT_DIR / "dist" / "RAIV.app"
BUNDLE_IDENTIFIER = "jp.raiv.viewer"
LICENSES_DIR = ROOT_DIR / "build" / "licenses"


def prepare_license_files(bundle_engine: bool) -> Path | None:
    shutil.rmtree(LICENSES_DIR, ignore_errors=True)
    LICENSES_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    project_license = ROOT_DIR / "LICENSE"
    if project_license.exists():
        shutil.copy2(project_license, LICENSES_DIR / "RAIV-MIT.txt")
        copied += 1
    if bundle_engine:
        realcugan_license = ROOT_DIR / "test" / "engines" / "realcugan-ncnn-vulkan-20220728-macos" / "LICENSE"
        if realcugan_license.exists():
            shutil.copy2(realcugan_license, LICENSES_DIR / "realcugan-ncnn-vulkan-MIT.txt")
            copied += 1
    notice = LICENSES_DIR / "README.txt"
    notice.write_text(
        "RAIV third-party notices.\n\n"
        "Public builds do not bundle realcugan-ncnn-vulkan by default.\n"
        "If you build with --bundle-engine, keep the included MIT license notice with any redistributed app bundle.\n"
        "Without a bundled engine, set RAIV_REALCUGAN_PATH to a local realcugan-ncnn-vulkan executable.\n",
        encoding="utf-8",
    )
    copied += 1
    return LICENSES_DIR if copied else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a local RAIV.app bundle.")
    parser.add_argument("--bundle-engine", action="store_true", help="bundle local test/engines into the app")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if platform.system() != "Darwin":
        raise SystemExit("macOS .app builds must run on macOS.")
    if not ENTRYPOINT.exists():
        raise SystemExit(f"missing entrypoint: {ENTRYPOINT}")
    shutil.rmtree(ROOT_DIR / "build", ignore_errors=True)
    shutil.rmtree(DIST_APP, ignore_errors=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
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
        str(ENTRYPOINT),
    ]
    licenses_dir = prepare_license_files(args.bundle_engine)
    if licenses_dir is not None:
        command[4:4] = ["--add-data", f"{licenses_dir}:licenses"]
    engines_dir = ROOT_DIR / "test" / "engines"
    if args.bundle_engine and engines_dir.exists():
        command[4:4] = ["--add-data", f"{engines_dir}:engines"]
    subprocess.run(command, cwd=ROOT_DIR, check=True)
    if not DIST_APP.exists():
        raise SystemExit(f"app build did not create {DIST_APP}")
    print(f"built: {DIST_APP}")


if __name__ == "__main__":
    main()

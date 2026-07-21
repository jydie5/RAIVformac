from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ENGINE_VERSION = "20220728"
ENGINE_PACKAGE_NAME = f"realcugan-ncnn-vulkan-{ENGINE_VERSION}-macos"
ENGINE_ARCHIVE_NAME = f"{ENGINE_PACKAGE_NAME}.zip"
ENGINE_ARCHIVE_URL = (
    "https://github.com/nihui/realcugan-ncnn-vulkan/releases/download/"
    f"{ENGINE_VERSION}/{ENGINE_ARCHIVE_NAME}"
)
ENGINE_ARCHIVE_SHA256 = "0df908cbb98b480f85897221b96d37b0bdb70f82d81b2c7037fe950dd5c0fa33"
ENGINE_EXECUTABLE_SHA256 = "a59aa9acd89115e33d7d71d7e413b405237833f331bdc87d4e20099af0e5e819"
DEFAULT_DESTINATION = ROOT_DIR / "build" / "vendor"
DEFAULT_CACHE_DIR = Path.home() / "Library" / "Caches" / "RAIV" / "vendor"

LICENSE_SOURCES = (
    (
        "Real-CUGAN-models-MIT.txt",
        "https://raw.githubusercontent.com/bilibili/ailab/680c4a26444f0ff2c7c6bae3b0712f3b478c8184/Real-CUGAN/LICENSE",
        "8cad8cfdf94baaf23519061af913770e52476ddec2a311e9510582e7bed13cba",
    ),
    (
        "ncnn-LICENSE.txt",
        "https://raw.githubusercontent.com/Tencent/ncnn/066614351391d309c96ae1e00c6fb1bd873b4949/LICENSE.txt",
        "6495f972a09ad7f64ccd953e79adba91a93d862edc7135e6d95210bbf4002a01",
    ),
    (
        "libwebp-COPYING.txt",
        "https://raw.githubusercontent.com/webmproject/libwebp/b9d2f9cd3bec5b0970edeb11ea03c0a4ea06e332/COPYING",
        "5aec868f669e384a22372a4e8a1a6cd7d44c64cd451f960ca69cc170d1e13acf",
    ),
    (
        "libwebp-PATENTS.txt",
        "https://raw.githubusercontent.com/webmproject/libwebp/b9d2f9cd3bec5b0970edeb11ea03c0a4ea06e332/PATENTS",
        "cc3273e0694ea5896145e0677699b53471b03ea43021ddc50e7923fbb9f5023c",
    ),
    (
        "MoltenVK-Apache-2.0.txt",
        "https://raw.githubusercontent.com/KhronosGroup/MoltenVK/v1.1.1/LICENSE",
        "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    ),
    (
        "LLVM-OpenMP-Apache-2.0-with-LLVM-exceptions.txt",
        "https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-11.0.0/llvm/LICENSE.TXT",
        "8d85c1057d742e597985c7d4e6320b015a9139385cff4cbae06ffc0ebe89afee",
    ),
    (
        "Qt-PySide6-LGPL-3.0-only.txt",
        "https://raw.githubusercontent.com/qtproject/pyside-pyside-setup/v6.11.1/LICENSES/LGPL-3.0-only.txt",
        "da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(url: str, destination: Path, expected_sha256: str) -> Path:
    if destination.exists() and sha256_file(destination) == expected_sha256:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "RAIV-for-mac-build/0.2"})
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output)
    actual_sha256 = sha256_file(temporary)
    if actual_sha256 != expected_sha256:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"SHA256 mismatch for {url}: {actual_sha256}")
    temporary.replace(destination)
    return destination


def extract_verified_archive(archive: Path, destination: Path) -> Path:
    package_dir = destination / ENGINE_PACKAGE_NAME
    if package_dir.exists():
        executable = package_dir / "realcugan-ncnn-vulkan"
        if executable.is_file() and sha256_file(executable) == ENGINE_EXECUTABLE_SHA256:
            return package_dir
        shutil.rmtree(package_dir)
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with zipfile.ZipFile(archive) as zip_file:
        for member in zip_file.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination_root):
                raise RuntimeError(f"unsafe archive member: {member.filename}")
        zip_file.extractall(destination)
    executable = package_dir / "realcugan-ncnn-vulkan"
    actual_sha256 = sha256_file(executable)
    if actual_sha256 != ENGINE_EXECUTABLE_SHA256:
        raise RuntimeError(f"unexpected Real-CUGAN executable SHA256: {actual_sha256}")
    executable.chmod(executable.stat().st_mode | 0o111)
    required = [
        package_dir / "LICENSE",
        package_dir / "README.md",
        package_dir / "models-se" / "up2x-no-denoise.bin",
        package_dir / "models-pro" / "up3x-denoise3x.bin",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("official Real-CUGAN package is incomplete: " + ", ".join(missing))
    return package_dir


def fetch_license_files(destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for filename, url, expected_sha256 in LICENSE_SOURCES:
        files.append(download_verified(url, destination / filename, expected_sha256))
    return files


def ensure_realcugan(destination: Path = DEFAULT_DESTINATION, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    archive = download_verified(
        ENGINE_ARCHIVE_URL,
        cache_dir / ENGINE_ARCHIVE_NAME,
        ENGINE_ARCHIVE_SHA256,
    )
    return extract_verified_archive(archive, destination)


def write_provenance(destination: Path, engine_dir: Path) -> Path:
    payload = {
        "component": "realcugan-ncnn-vulkan",
        "version": ENGINE_VERSION,
        "source": ENGINE_ARCHIVE_URL,
        "archive_sha256": ENGINE_ARCHIVE_SHA256,
        "executable_sha256": sha256_file(engine_dir / "realcugan-ncnn-vulkan"),
        "upstream": "https://github.com/nihui/realcugan-ncnn-vulkan",
        "model_source": "https://github.com/bilibili/ailab/tree/main/Real-CUGAN",
    }
    path = destination / "realcugan-provenance.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the pinned official Real-CUGAN macOS package.")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--licenses", type=Path)
    args = parser.parse_args()
    engine_dir = ensure_realcugan(args.destination)
    print(engine_dir)
    if args.licenses is not None:
        fetch_license_files(args.licenses)
        write_provenance(args.licenses, engine_dir)


if __name__ == "__main__":
    main()

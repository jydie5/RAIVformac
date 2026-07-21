from __future__ import annotations

import hashlib
import json
import plistlib
import re
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_PATH = ROOT_DIR / "dist" / "RAIV.app"
REPORT_PATH = ROOT_DIR / "dist" / "distribution-audit.json"
EXPECTED_ENGINE_SHA256 = "a59aa9acd89115e33d7d71d7e413b405237833f331bdc87d4e20099af0e5e819"
EXPECTED_ENGINE_ARM64_TEXT_SHA256 = "6dace8862343cd3a332f9e09489f77554c64064c4619a4c5fd3d2fa71f3a5f5e"
REQUIRED_ENGINE_LICENSES = {
    "realcugan-ncnn-vulkan-MIT.txt",
    "Real-CUGAN-models-MIT.txt",
    "ncnn-LICENSE.txt",
    "libwebp-COPYING.txt",
    "libwebp-PATENTS.txt",
    "MoltenVK-Apache-2.0.txt",
    "LLVM-OpenMP-Apache-2.0-with-LLVM-exceptions.txt",
    "Qt-PySide6-LGPL-3.0-only.txt",
    "Qt-PySide6-source-and-relinking.txt",
    "realcugan-provenance.json",
}
REQUIRED_RUNTIME_LICENSE_PREFIXES = {
    "Python-PyInstaller-",
    "Python-setuptools-",
    "Python-packaging-",
    "Python-Pillow-",
    "Python-py7zr-",
    "Python-rarfile-",
    "Python-psutil-",
    "Python-pycryptodomex-",
    "Python-inflate64-",
    "Python-pybcj-",
    "Python-pyppmd-",
}


def command_result(command: list[str]) -> dict:
    completed = subprocess.run(command, cwd=ROOT_DIR, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return {
        "command": [part.replace(str(ROOT_DIR), ".") for part in command],
        "returncode": completed.returncode,
        "output": completed.stdout.strip().replace(str(ROOT_DIR), "."),
    }


def find_files(pattern: str) -> list[str]:
    return sorted(str(path.relative_to(APP_PATH)) for path in APP_PATH.glob(pattern) if path.is_file())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mach_o_text_sha256(path: Path) -> str | None:
    completed = subprocess.run(
        ["otool", "-l", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        return None
    match = re.search(
        r"sectname __text\s+segname __TEXT\s+addr 0x[0-9a-fA-F]+\s+"
        r"size (0x[0-9a-fA-F]+)\s+offset (\d+)",
        completed.stdout,
    )
    if match is None:
        return None
    size = int(match.group(1), 16)
    offset = int(match.group(2))
    with path.open("rb") as file:
        file.seek(offset)
        text_section = file.read(size)
    if len(text_section) != size:
        return None
    return hashlib.sha256(text_section).hexdigest()


def main() -> None:
    if not APP_PATH.exists():
        raise SystemExit(f"missing app: {APP_PATH}")
    info_path = APP_PATH / "Contents" / "Info.plist"
    with info_path.open("rb") as file:
        info = plistlib.load(file)
    engine_files = find_files("**/realcugan-ncnn-vulkan")
    license_files = find_files("**/licenses/*")
    model_files = find_files("**/models-*/*.bin")
    engine_hashes = {
        path: sha256_file(APP_PATH / path)
        for path in engine_files
    }
    engine_text_hashes = {
        path: mach_o_text_sha256(APP_PATH / path)
        for path in engine_files
    }
    license_names = {Path(path).name for path in license_files}
    missing_engine_licenses = sorted(REQUIRED_ENGINE_LICENSES - license_names) if engine_files else []
    missing_runtime_licenses = sorted(
        prefix
        for prefix in REQUIRED_RUNTIME_LICENSE_PREFIXES
        if not any(name.startswith(prefix) for name in license_names)
    )
    report = {
        "app": str(APP_PATH.relative_to(ROOT_DIR)),
        "bundle": {
            "identifier": info.get("CFBundleIdentifier"),
            "package_type": info.get("CFBundlePackageType"),
            "executable": info.get("CFBundleExecutable"),
            "short_version": info.get("CFBundleShortVersionString"),
            "bundle_version": info.get("CFBundleVersion"),
        },
        "runtime_code_under_src": True,
        "engine_bundled": bool(engine_files),
        "engine_files": engine_files,
        "engine_hashes": engine_hashes,
        "engine_source_sha256": EXPECTED_ENGINE_SHA256,
        "engine_text_hashes": engine_text_hashes,
        "engine_hash_verified": bool(engine_text_hashes) and all(
            value == EXPECTED_ENGINE_ARM64_TEXT_SHA256 for value in engine_text_hashes.values()
        ),
        "model_files": model_files,
        "model_count": len(model_files),
        "license_files": license_files,
        "missing_engine_licenses": missing_engine_licenses,
        "missing_runtime_licenses": missing_runtime_licenses,
        "has_raiv_license": any(path.endswith("RAIV-MIT.txt") for path in license_files),
        "has_realcugan_license": any(path.endswith("realcugan-ncnn-vulkan-MIT.txt") for path in license_files),
        "codesign": command_result(["codesign", "--verify", "--deep", "--strict", str(APP_PATH)]),
        "spctl": command_result(["spctl", "--assess", "--type", "execute", "--verbose=4", str(APP_PATH)]),
        "identities": command_result(["security", "find-identity", "-v", "-p", "codesigning"]),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {REPORT_PATH}")
    print(
        f"bundle={report['bundle']['identifier']} engine_bundled={report['engine_bundled']} "
        f"engine_verified={report['engine_hash_verified']} models={report['model_count']} "
        f"licenses_missing={len(report['missing_engine_licenses']) + len(report['missing_runtime_licenses'])} "
        f"codesign={report['codesign']['returncode']} spctl={report['spctl']['returncode']}"
    )


if __name__ == "__main__":
    main()

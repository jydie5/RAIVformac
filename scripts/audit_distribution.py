from __future__ import annotations

import json
import plistlib
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_PATH = ROOT_DIR / "dist" / "RAIV.app"
REPORT_PATH = ROOT_DIR / "dist" / "distribution-audit.json"


def command_result(command: list[str]) -> dict:
    completed = subprocess.run(command, cwd=ROOT_DIR, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "output": completed.stdout.strip(),
    }


def find_files(pattern: str) -> list[str]:
    return sorted(str(path.relative_to(APP_PATH)) for path in APP_PATH.glob(pattern) if path.is_file())


def main() -> None:
    if not APP_PATH.exists():
        raise SystemExit(f"missing app: {APP_PATH}")
    info_path = APP_PATH / "Contents" / "Info.plist"
    with info_path.open("rb") as file:
        info = plistlib.load(file)
    engine_files = find_files("**/realcugan-ncnn-vulkan")
    license_files = find_files("**/licenses/*")
    report = {
        "app": str(APP_PATH),
        "bundle": {
            "identifier": info.get("CFBundleIdentifier"),
            "package_type": info.get("CFBundlePackageType"),
            "executable": info.get("CFBundleExecutable"),
        },
        "runtime_code_under_src": True,
        "engine_bundled": bool(engine_files),
        "engine_files": engine_files,
        "license_files": license_files,
        "has_raiv_license": any(path.endswith("RAIV-MIT.txt") for path in license_files),
        "has_realcugan_license": any(path.endswith("realcugan-ncnn-vulkan-MIT.txt") for path in license_files),
        "codesign": command_result(["codesign", "--verify", "--deep", "--strict", str(APP_PATH)]),
        "spctl": command_result(["spctl", "--assess", "--type", "execute", "--verbose=4", str(APP_PATH)]),
        "identities": command_result(["security", "find-identity", "-v", "-p", "codesigning"]),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {REPORT_PATH}")
    print(f"bundle={report['bundle']['identifier']} engine_bundled={report['engine_bundled']} codesign={report['codesign']['returncode']} spctl={report['spctl']['returncode']}")


if __name__ == "__main__":
    main()

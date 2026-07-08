from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_PATH = ROOT_DIR / "dist" / "RAIV.app"
ARCHIVE_PATH = ROOT_DIR / "dist" / "RAIV-notary.zip"
REPORT_PATH = ROOT_DIR / "dist" / "release-check.json"
ENTITLEMENTS = ROOT_DIR / "scripts" / "raiv.entitlements.plist"


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(
        command,
        cwd=ROOT_DIR,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def capture(command: list[str]) -> tuple[int, str]:
    completed = run(command, check=False)
    output = completed.stdout.strip()
    if output:
        print(output)
    return completed.returncode, output


def build_app(bundle_engine: bool) -> None:
    command = [sys.executable, "scripts/build_macos_app.py"]
    if bundle_engine:
        command.append("--bundle-engine")
    run(command)


def find_developer_id_identities() -> list[str]:
    code, output = capture(["security", "find-identity", "-v", "-p", "codesigning"])
    if code != 0:
        return []
    identities: list[str] = []
    for line in output.splitlines():
        match = re.search(r'"(Developer ID Application:[^"]+)"', line)
        if match:
            identities.append(match.group(1))
    return identities


def resolve_identity(identity: str) -> str:
    identities = find_developer_id_identities()
    if identity == "auto":
        if len(identities) == 1:
            print(f"using identity: {identities[0]}")
            return identities[0]
        if not identities:
            raise SystemExit("no Developer ID Application identity found in Keychain")
        raise SystemExit("multiple Developer ID Application identities found; pass --identity explicitly:\n" + "\n".join(identities))
    if identity not in identities:
        raise SystemExit(
            f"codesigning identity not found: {identity}\n"
            "Install a Developer ID Application certificate in Keychain first."
        )
    return identity


def ensure_notary_profile(profile: str) -> None:
    code, output = capture(["xcrun", "notarytool", "history", "--keychain-profile", profile, "--output-format", "json"])
    if code != 0:
        raise SystemExit(
            f"notary profile is not usable: {profile}\n"
            "Create it with: xcrun notarytool store-credentials "
            f"{profile} --apple-id APPLE_ID --team-id TEAM_ID --password APP_SPECIFIC_PASSWORD"
        )


def sign_app(identity: str) -> None:
    run(
        [
            "codesign",
            "--force",
            "--deep",
            "--timestamp",
            "--options",
            "runtime",
            "--entitlements",
            str(ENTITLEMENTS),
            "--sign",
            identity,
            str(APP_PATH),
        ]
    )
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(APP_PATH)])


def make_archive() -> None:
    ARCHIVE_PATH.unlink(missing_ok=True)
    run(["ditto", "-c", "-k", "--keepParent", str(APP_PATH), str(ARCHIVE_PATH)])


def notarize(profile: str) -> dict:
    completed = run(
        [
            "xcrun",
            "notarytool",
            "submit",
            str(ARCHIVE_PATH),
            "--keychain-profile",
            profile,
            "--wait",
            "--output-format",
            "json",
        ]
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"raw": completed.stdout}
    status = payload.get("status")
    if status and status != "Accepted":
        raise SystemExit(f"notarization failed: {status}\n{completed.stdout}")
    return payload


def staple_and_assess() -> tuple[int, str]:
    run(["xcrun", "stapler", "staple", str(APP_PATH)])
    run(["xcrun", "stapler", "validate", str(APP_PATH)])
    return capture(["spctl", "--assess", "--type", "execute", "--verbose=4", str(APP_PATH)])


def write_report(payload: dict, spctl_code: int, spctl_output: str) -> None:
    report = {
        "app": str(APP_PATH),
        "archive": str(ARCHIVE_PATH),
        "notary": payload,
        "spctl": {
            "code": spctl_code,
            "output": spctl_output,
        },
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {REPORT_PATH}")


def audit_distribution() -> None:
    run([sys.executable, "scripts/audit_distribution.py"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build, Developer ID sign, notarize, staple, and assess RAIV.app.")
    parser.add_argument("--identity", required=True, help='codesigning identity, or "auto" when exactly one Developer ID Application identity exists')
    parser.add_argument("--notary-profile", required=True, help="notarytool keychain profile name")
    parser.add_argument("--skip-build", action="store_true", help="use existing dist/RAIV.app")
    parser.add_argument("--skip-notary", action="store_true", help="sign and archive only")
    parser.add_argument("--bundle-engine", action="store_true", help="bundle local Real-CUGAN engine; requires license review")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    identity = resolve_identity(args.identity)
    if not args.skip_notary:
        ensure_notary_profile(args.notary_profile)
    if not args.skip_build:
        build_app(args.bundle_engine)
    if not APP_PATH.exists():
        raise SystemExit(f"missing app: {APP_PATH}")
    sign_app(identity)
    make_archive()
    notary_payload: dict = {"skipped": True}
    spctl_code, spctl_output = capture(["spctl", "--assess", "--type", "execute", "--verbose=4", str(APP_PATH)])
    if not args.skip_notary:
        notary_payload = notarize(args.notary_profile)
        spctl_code, spctl_output = staple_and_assess()
    write_report(notary_payload, spctl_code, spctl_output)
    audit_distribution()
    if not args.skip_notary and spctl_code != 0:
        raise SystemExit(spctl_code)


if __name__ == "__main__":
    main()

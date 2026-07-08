from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT_DIR / "dist" / "distribution-audit.json"
RELEASE_PATH = ROOT_DIR / "dist" / "release-check.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"missing required report: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail unless RAIV is ready for public macOS distribution.")
    parser.add_argument("--allow-bundled-engine", action="store_true", help="allow engine files in the release artifact")
    args = parser.parse_args()

    audit = load_json(AUDIT_PATH)
    release = load_json(RELEASE_PATH)
    failures: list[str] = []

    bundle = audit.get("bundle", {})
    if bundle.get("package_type") != "APPL":
        failures.append("bundle package type is not APPL")
    if bundle.get("identifier") != "jp.raiv.viewer":
        failures.append("bundle identifier is not jp.raiv.viewer")
    if audit.get("codesign", {}).get("returncode") != 0:
        failures.append("codesign verification did not pass")
    if audit.get("spctl", {}).get("returncode") != 0:
        failures.append("Gatekeeper assessment did not accept the app")
    identity_output = audit.get("identities", {}).get("output", "")
    developer_ids = re.findall(r'"Developer ID Application:[^"]+"', identity_output)
    if not developer_ids:
        failures.append("Developer ID Application identity is not visible in Keychain")
    if audit.get("engine_bundled") and not args.allow_bundled_engine:
        failures.append("engine is bundled without --allow-bundled-engine")
    if audit.get("engine_bundled") and not audit.get("has_realcugan_license"):
        failures.append("engine is bundled but Real-CUGAN license notice is missing")

    notary = release.get("notary", {})
    if notary.get("skipped"):
        failures.append("notarization was skipped")
    if notary.get("status") != "Accepted":
        failures.append("notarization status is not Accepted")
    if release.get("spctl", {}).get("code") != 0:
        failures.append("post-staple Gatekeeper assessment did not accept the app")

    if failures:
        print("release_ready=false")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("release_ready=true")


if __name__ == "__main__":
    main()

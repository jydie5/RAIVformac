from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_PATH = ROOT_DIR / "dist" / "RAIV.app"
AUDIT_PATH = ROOT_DIR / "dist" / "distribution-audit.json"
DEFAULT_VERSION = "0.3.0-alpha"
FORBIDDEN_ARCHIVE_TERMS = (
    "sample/",
    "test/",
    "__pycache__",
    ".ds_store",
)


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_audit(audit: dict) -> list[str]:
    failures: list[str] = []
    if audit.get("bundle", {}).get("identifier") != "jp.raiv.viewer":
        failures.append("unexpected bundle identifier")
    if not audit.get("engine_bundled"):
        failures.append("Real-CUGAN is not bundled")
    if not audit.get("engine_hash_verified"):
        failures.append("Real-CUGAN executable hash is not verified")
    if audit.get("model_count", 0) < 19:
        failures.append("Real-CUGAN model set is incomplete")
    if audit.get("missing_engine_licenses"):
        failures.append("third-party license files are missing")
    if audit.get("missing_runtime_licenses"):
        failures.append("Python runtime dependency license files are missing")
    if not audit.get("has_raiv_license"):
        failures.append("RAIV license is missing")
    if audit.get("codesign", {}).get("returncode") != 0:
        failures.append("ad-hoc code-signature verification failed")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the unsigned Python-free RAIV standalone ZIP.")
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    if not args.skip_build:
        run([sys.executable, "scripts/build_macos_app.py", "--bundle-engine"])
    if not APP_PATH.is_dir():
        raise SystemExit(f"missing app: {APP_PATH}")
    run([sys.executable, "scripts/audit_distribution.py"])
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    failures = check_audit(audit)
    if failures:
        raise SystemExit("standalone audit failed:\n- " + "\n- ".join(failures))

    artifact = ROOT_DIR / "dist" / f"RAIVformac-v{args.version}-macos-apple-silicon-standalone.zip"
    checksum_path = artifact.with_suffix(artifact.suffix + ".sha256")
    artifact.unlink(missing_ok=True)
    run(["ditto", "-c", "-k", "--norsrc", "--keepParent", str(APP_PATH), str(artifact)])
    with zipfile.ZipFile(artifact) as archive:
        lowered_names = [name.lower() for name in archive.namelist()]
    leaked = sorted(
        name
        for name in lowered_names
        if any(term.lower() in name for term in FORBIDDEN_ARCHIVE_TERMS)
    )
    if leaked:
        raise SystemExit("forbidden paths found in release archive:\n" + "\n".join(leaked[:20]))

    checksum = sha256_file(artifact)
    checksum_path.write_text(f"{checksum}  {artifact.name}\n", encoding="ascii")
    manifest = {
        "version": args.version,
        "artifact": artifact.name,
        "artifact_sha256": checksum,
        "python_required_for_end_user": False,
        "engine_bundled": True,
        "engine_hash_verified": True,
        "model_count": audit.get("model_count"),
        "license_files": audit.get("license_files"),
        "unsigned": True,
        "alpha_release_ready": True,
    }
    manifest_path = ROOT_DIR / "dist" / "standalone-release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"artifact: {artifact}")
    print(f"sha256: {checksum}")
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description="Store Apple notary credentials in the local Keychain.")
    parser.add_argument("--profile", default="RAIV-notary")
    parser.add_argument("--apple-id", required=True)
    parser.add_argument("--team-id", required=True)
    args = parser.parse_args()

    command = [
        "xcrun",
        "notarytool",
        "store-credentials",
        args.profile,
        "--apple-id",
        args.apple_id,
        "--team-id",
        args.team_id,
    ]
    print("+ " + " ".join(command) + " --password <secure prompt>", flush=True)
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()

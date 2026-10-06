"""
Build and sign a release (run on Windows, from the project root, venv active).

    python -m scripts.build_release --tag v1.0.0 --key C:\\secure\\hcs_signing.key

Steps: check tag == version.py, build the updater helper, build the main app
(which bundles the helper), then write dist/HealthCenterSystem.exe.sha256 and
.sig. Upload ALL THREE files to a new GitHub Release with that tag.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from scripts.sign_release import sign_file
from updater import settings
from version import __version__

ROOT = Path(__file__).resolve().parent.parent


def _pyinstaller(spec: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", spec, "--clean", "--noconfirm"], cwd=ROOT, check=True
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--key", required=True, type=Path)
    args = parser.parse_args()

    if args.tag != f"v{__version__}":
        print(f"Tag {args.tag} does not match version.py (expected v{__version__}).")
        return 1
    if not settings.SIGNING_PUBLIC_KEY_HEX or "CHANGE_ME" in (settings.GITHUB_OWNER, settings.GITHUB_REPO):
        print("Fill in GITHUB_OWNER, GITHUB_REPO and SIGNING_PUBLIC_KEY_HEX in updater/settings.py first.")
        return 1

    _pyinstaller("HealthCenterUpdater.spec")
    _pyinstaller("HealthCenterSystem.spec")

    exe = ROOT / "dist" / settings.APP_EXE_NAME
    checksum_file, signature_file = sign_file(exe, args.tag, args.key)
    print("\nUpload these three files to the GitHub Release:")
    for path in (exe, checksum_file, signature_file):
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

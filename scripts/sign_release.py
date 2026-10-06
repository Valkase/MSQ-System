"""
Create the .sha256 and .sig files that must be uploaded next to the exe.

    python -m scripts.sign_release dist\\HealthCenterSystem.exe v1.0.0 C:\\secure\\hcs_signing.key

Normally called by scripts/build_release.py.
"""

import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from updater.checksum import sha256_file, signing_message


def sign_file(exe_path: Path, tag: str, key_path: Path) -> tuple[Path, Path]:
    private = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(Path(key_path).read_text(encoding="ascii").strip())
    )
    digest = sha256_file(exe_path)
    checksum_file = exe_path.with_name(exe_path.name + ".sha256")
    signature_file = exe_path.with_name(exe_path.name + ".sig")
    checksum_file.write_text(f"{digest}  {exe_path.name}\n", encoding="ascii")
    signature_file.write_bytes(private.sign(signing_message(tag, digest)))
    return checksum_file, signature_file


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    checksum_file, signature_file = sign_file(Path(argv[1]), argv[2], Path(argv[3]))
    print(f"Wrote {checksum_file}\nWrote {signature_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

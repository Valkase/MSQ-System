"""
One-time setup: create the Ed25519 key pair used to sign releases.

    python -m scripts.generate_signing_key C:\\secure\\hcs_signing.key

Writes the PRIVATE key (hex) to the path you give and prints the PUBLIC key,
which you paste into updater/settings.py as SIGNING_PUBLIC_KEY_HEX.
Keep the private key OFFLINE (a flash drive in a safe is fine) and NEVER
commit it. If it is lost you can't sign updates: you would have to ship a new
public key by manually installing a new build on every desk.
"""

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    target = Path(argv[1])
    if target.exists():
        print(f"Refusing to overwrite existing file: {target}")
        return 1

    private = Ed25519PrivateKey.generate()
    private_hex = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    ).hex()
    public_hex = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()

    target.write_text(private_hex + "\n", encoding="ascii")
    print(f"Private key written to {target} (keep it offline, never commit it).")
    print("Put this in updater/settings.py:")
    print(f'SIGNING_PUBLIC_KEY_HEX = "{public_hex}"')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""
Release verification (task plan Phase 5: "Publish a checksum alongside each
release and write the verification step").

Two independent checks, BOTH required:
1. SHA-256 of the downloaded file must match the published .sha256 file
   (catches corruption / truncation).
2. An Ed25519 signature over the digest must verify against the public key
   embedded in the app (catches a compromised GitHub account replacing both
   the exe and its checksum: the attacker doesn't have the offline private key).

What is signed is not the whole exe but  "HCS-UPDATE-v1\\n<tag>\\n<sha256 hex>",
so a signature is also bound to its release tag and can't be replayed onto a
different version. scripts/sign_release.py uses the same signing_message().
"""

import hashlib
import re
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class VerificationError(Exception):
    """Base class: the downloaded update must NOT be installed."""


class ChecksumError(VerificationError):
    pass


class SignatureError(VerificationError):
    pass


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksum_file(text: str) -> str:
    """Accepts "<hex>" or "<hex>  <filename>" (sha256sum format). Returns lowercase hex."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            token = line.split()[0]
            if _HEX64.match(token):
                return token.lower()
            break
    raise ChecksumError("Checksum file is not a valid SHA-256 digest")


def signing_message(tag: str, digest_hex: str) -> bytes:
    return f"HCS-UPDATE-v1\n{tag}\n{digest_hex.lower()}".encode("utf-8")


def verify_checksum(path: Path, expected_hex: str) -> str:
    actual = sha256_file(path)
    if actual != expected_hex.lower():
        raise ChecksumError("Downloaded file does not match its published checksum")
    return actual


def verify_signature(tag: str, digest_hex: str, signature: bytes, public_key_hex: str) -> None:
    if not public_key_hex:
        raise SignatureError("No signing public key is configured; refusing to install")
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
    except ValueError as exc:
        raise SignatureError("Configured signing public key is invalid") from exc
    try:
        key.verify(signature, signing_message(tag, digest_hex))
    except InvalidSignature as exc:
        raise SignatureError("Release signature is invalid") from exc


def verify_release_file(
    path: Path, tag: str, checksum_text: str, signature: bytes, public_key_hex: str
) -> None:
    """Raises VerificationError (ChecksumError / SignatureError) unless both checks pass."""
    expected = parse_checksum_file(checksum_text)
    actual = verify_checksum(path, expected)
    verify_signature(tag, actual, signature, public_key_hex)

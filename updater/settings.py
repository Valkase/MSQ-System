"""
Updater settings. Fill in the two CHANGE_ME values before the first release.

SIGNING_PUBLIC_KEY_HEX is the Ed25519 PUBLIC key (64 hex chars) printed by
scripts/generate_signing_key.py. It is safe to publish; the matching private
key must stay offline and out of the repository. While it is empty the app
refuses to install any update.
"""

GITHUB_OWNER = "Valkase"
GITHUB_REPO = "https://github.com/Valkase/MSQ-System"

# Release asset names. Each release must contain all three.
APP_EXE_NAME = "HealthCenterSystem.exe"
CHECKSUM_ASSET_NAME = APP_EXE_NAME + ".sha256"
SIGNATURE_ASSET_NAME = APP_EXE_NAME + ".sig"

SIGNING_PUBLIC_KEY_HEX = "Ed25519"

USER_AGENT = "HealthCenterSystem-Updater"
CHECK_TIMEOUT_SECONDS = 10
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_EXE_BYTES = 500 * 1024 * 1024
MAX_SMALL_FILE_BYTES = 64 * 1024

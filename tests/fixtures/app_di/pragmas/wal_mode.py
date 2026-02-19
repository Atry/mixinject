"""WalMode: contributes WAL journal mode pragma."""

from overlay.language import patch


@patch
def startup_pragmas() -> str:
    return "PRAGMA journal_mode=WAL"

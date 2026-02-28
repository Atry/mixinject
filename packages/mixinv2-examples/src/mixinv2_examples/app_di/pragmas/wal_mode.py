"""WalMode: contributes WAL journal mode pragma."""

from mixinv2 import patch


@patch
def startup_pragmas() -> str:
    return "PRAGMA journal_mode=WAL"

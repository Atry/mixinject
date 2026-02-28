"""ForeignKeys: contributes foreign key enforcement pragma."""

from mixinv2 import patch


@patch
def startup_pragmas() -> str:
    return "PRAGMA foreign_keys=ON"

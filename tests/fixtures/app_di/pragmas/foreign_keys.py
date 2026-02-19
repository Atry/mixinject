"""ForeignKeys: contributes foreign key enforcement pragma."""

from overlay.language import patch


@patch
def startup_pragmas() -> str:
    return "PRAGMA foreign_keys=ON"

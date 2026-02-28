"""UserVersionPragma: contributes user_version pragma, depends on schema_version."""

from mixinv2 import extern, patch


@extern
def schema_version() -> int: ...


@patch
def startup_pragmas(schema_version: int) -> str:
    return f"PRAGMA user_version={schema_version}"

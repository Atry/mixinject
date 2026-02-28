"""connection.execute(sql, parameters).fetchone() -> single row"""

import sqlite3

from mixinv2 import extern, public, resource


@extern
def connection() -> sqlite3.Connection: ...


@extern
def sql() -> str: ...


@extern
def parameters() -> tuple: ...


@public
@resource
def row(connection: sqlite3.Connection, sql: str, parameters: tuple) -> tuple:
    result = connection.execute(sql, parameters).fetchone()
    assert result is not None, f"query returned no rows: {sql}"
    return result

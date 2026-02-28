"""connection.execute(sql).fetchall() -> single scalar value"""

import sqlite3

from mixinv2 import extern, public, resource


@extern
def connection() -> sqlite3.Connection: ...


@extern
def sql() -> str: ...


@public
@resource
def scalar(connection: sqlite3.Connection, sql: str) -> object:
    row, = connection.execute(sql).fetchall()
    value, = row
    return value

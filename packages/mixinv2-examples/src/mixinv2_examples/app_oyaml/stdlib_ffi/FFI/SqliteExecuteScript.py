"""connection.executescript(sql) -> connection (returns same connection)"""

import sqlite3

from mixinv2 import extern, public, resource


@extern
def connection() -> sqlite3.Connection: ...


@extern
def sql() -> str: ...


@public
@resource
def executed(connection: sqlite3.Connection, sql: str) -> sqlite3.Connection:
    connection.executescript(sql)
    return connection

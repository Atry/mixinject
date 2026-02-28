"""sqlite3.connect(database_path) + executescript(setup_sql) -> connection"""

import sqlite3

from mixinv2 import extern, public, resource


@extern
def database_path() -> str: ...


@extern
def setup_sql() -> str: ...


@public
@resource
def connection(database_path: str, setup_sql: str) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path, check_same_thread=False)
    conn.executescript(setup_sql)
    return conn

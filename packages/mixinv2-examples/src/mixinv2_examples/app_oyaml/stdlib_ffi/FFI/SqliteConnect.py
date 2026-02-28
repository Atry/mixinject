"""sqlite3.connect(database_path, check_same_thread=False)"""

import sqlite3

from mixinv2 import extern, public, resource


@extern
def database_path() -> str: ...


@public
@resource
def connection(database_path: str) -> sqlite3.Connection:
    return sqlite3.connect(database_path, check_same_thread=False)

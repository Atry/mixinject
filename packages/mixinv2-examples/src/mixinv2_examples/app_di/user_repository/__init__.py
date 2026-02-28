"""UserRepository: app-scoped business resources over the database."""

import sqlite3

from mixinv2 import extern, public, resource


@extern
def connection() -> sqlite3.Connection: ...


@public
@resource
def user_count(connection: sqlite3.Connection) -> int:
    (count,) = connection.execute("SELECT COUNT(*) FROM users").fetchone()
    return count

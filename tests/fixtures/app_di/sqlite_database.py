"""SQLiteDatabase module: owns database_path config, provides connection."""

import sqlite3

from overlay.language import extern, public, resource


@extern
def database_path() -> str: ...


@public
@resource
def connection(database_path: str) -> sqlite3.Connection:
    db = sqlite3.connect(database_path, check_same_thread=False)
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO users VALUES (1, 'alice')")
    db.execute("INSERT INTO users VALUES (2, 'bob')")
    db.commit()
    return db

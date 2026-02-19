"""EagerDatabase: @eager resource that runs schema migration at startup."""

import sqlite3

from overlay.language import eager, public, resource


@public
@eager
@resource
def connection() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    db.commit()
    return db

"""UserRepository.RequestScope: per-request DB resources wired via union-mount."""

import sqlite3
from typing import Callable

from overlay.language import extern, public, resource


@extern
def user_id() -> int: ...  # provided by app_services.request_scope


@public
@resource
def current_user(
    connection: sqlite3.Connection, user_id: int, user: Callable
) -> object:
    row = connection.execute(
        "SELECT id, name FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    assert row is not None, f"no user with id={user_id}"
    identifier, name = row
    return user(user_id=identifier, name=name)

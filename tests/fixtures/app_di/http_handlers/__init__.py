"""HttpHandlers: HTTP request handling — no network/DB knowledge."""

from overlay.language import extern


@extern
def user_count() -> int: ...

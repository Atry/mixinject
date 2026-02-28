"""HttpHandlers: HTTP request handling — no network/DB knowledge."""

from mixinv2 import extern


@extern
def user_count() -> int: ...

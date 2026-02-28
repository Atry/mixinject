"""int(string) -> int"""

from mixinv2 import extern, public, resource


@extern
def string() -> str: ...


@public
@resource
def value(string: str) -> int:
    return int(string)

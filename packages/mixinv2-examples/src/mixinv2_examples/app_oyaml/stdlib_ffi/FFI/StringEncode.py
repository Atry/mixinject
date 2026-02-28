"""string.encode() -> bytes"""

from mixinv2 import extern, public, resource


@extern
def string() -> str: ...


@public
@resource
def encoded(string: str) -> bytes:
    return string.encode()

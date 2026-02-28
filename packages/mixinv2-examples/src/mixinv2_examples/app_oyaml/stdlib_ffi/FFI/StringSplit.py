"""string.split(separator) -> tuple of parts"""

from mixinv2 import extern, public, resource


@extern
def string() -> str: ...


@extern
def separator() -> str: ...


@public
@resource
def parts(string: str, separator: str) -> tuple:
    return tuple(string.split(separator))

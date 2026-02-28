"""(element,) -> 1-tuple"""

from mixinv2 import extern, public, resource


@extern
def element() -> object: ...


@public
@resource
def wrapped(element: object) -> tuple:
    return (element,)

"""sequence[index] -> element"""

from mixinv2 import extern, public, resource


@extern
def sequence() -> object: ...


@extern
def index() -> int: ...


@public
@resource
def element(sequence: object, index: int) -> object:
    return sequence[index]  # type: ignore[index]

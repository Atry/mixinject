"""sequence[index] -> element"""

from collections.abc import Awaitable

from mixinv2 import extern, public, resource

from ._async_resource import async_resource


@extern
def sequence() -> Awaitable[object]: ...


@extern
def index() -> int: ...


@public
@resource
@async_resource
async def element(sequence: object, index: int) -> object:
    return sequence[index]  # type: ignore[index]

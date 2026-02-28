"""(element,) -> 1-tuple"""

from collections.abc import Awaitable

from mixinv2 import extern, public, resource

from ._async_resource import async_resource


@extern
def element() -> Awaitable[object]: ...


@public
@resource
@async_resource
async def wrapped(element: object) -> tuple:
    return (element,)

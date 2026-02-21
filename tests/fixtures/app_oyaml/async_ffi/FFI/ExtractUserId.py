"""int(request.url.path.split(path_separator)[-1]) -> user_id"""

from collections.abc import Awaitable
from typing import Protocol

from overlay.language import extern, public, resource

from ._async_resource import async_resource


class _URL(Protocol):
    path: str


class _RequestWithURL(Protocol):
    url: _URL


@extern
def request() -> Awaitable[_RequestWithURL]: ...


@extern
def path_separator() -> Awaitable[str]: ...


@public
@resource
@async_resource
async def user_id(request: _RequestWithURL, path_separator: str) -> int:
    return int(request.url.path.split(path_separator)[-1])

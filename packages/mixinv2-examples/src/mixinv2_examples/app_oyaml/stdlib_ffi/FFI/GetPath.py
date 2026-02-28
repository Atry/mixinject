"""request.path -> str"""

from typing import Protocol

from mixinv2 import extern, public, resource


class _RequestWithPath(Protocol):
    path: str


@extern
def request() -> _RequestWithPath: ...


@public
@resource
def path(request: _RequestWithPath) -> str:
    return request.path

"""int(request.path.split(path_separator)[-1]) -> user_id"""

from typing import Protocol

from overlay.language import extern, public, resource


class _RequestWithPath(Protocol):
    path: str


@extern
def request() -> _RequestWithPath: ...


@extern
def path_separator() -> str: ...


@public
@resource
def user_id(request: _RequestWithPath, path_separator: str) -> int:
    return int(request.path.split(path_separator)[-1])

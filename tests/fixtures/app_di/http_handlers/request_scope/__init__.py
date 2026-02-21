"""HttpHandlers.RequestScope: extracts request-scoped values from the HTTP request."""

from http.server import BaseHTTPRequestHandler
from typing import Protocol

from overlay.language import extern, public, resource


class _RequestWithPath(Protocol):
    path: str


@extern
def request() -> BaseHTTPRequestHandler: ...


@extern
def current_user() -> object: ...


@public
@resource
def user_id(request: _RequestWithPath) -> int:
    return int(request.path.split("/")[-1])


@public
@resource
def response_body(user_count: int, current_user: object) -> bytes:
    return f"total={user_count} current={current_user.name}".encode()


@public
@resource
def response_sent(
    request: BaseHTTPRequestHandler,
    response_body: bytes,
) -> None:
    request.send_response(200)
    request.end_headers()
    request.wfile.write(response_body)

"""Create a BaseHTTPRequestHandler subclass that dispatches GET to RequestScope.response"""

from http.server import BaseHTTPRequestHandler
from typing import Protocol

from mixinv2 import public, resource


class _RequestScopeInstance(Protocol):
    response: object


class _RequestScopeFactory(Protocol):
    def __call__(self, request: BaseHTTPRequestHandler) -> _RequestScopeInstance: ...


@public
@resource
def handler_class(RequestScope: _RequestScopeFactory) -> type:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            RequestScope(request=self).response

        def log_message(self, format: str, *arguments: object) -> None:
            pass

    return Handler

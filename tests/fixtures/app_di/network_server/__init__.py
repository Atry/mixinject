"""NetworkServer: HTTP server, owns host/port config, no business logic."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from overlay.language import extern, public, resource


@extern
def host() -> str: ...


@extern
def port() -> int: ...


@public
@resource
def server(host: str, port: int, request_scope: Callable) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request_scope(request=self).response_sent

        def log_message(self, format: str, *arguments: object) -> None:
            pass

    return HTTPServer((host, port), Handler)

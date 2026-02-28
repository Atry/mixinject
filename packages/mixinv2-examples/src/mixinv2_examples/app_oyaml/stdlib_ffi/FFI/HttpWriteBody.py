"""request.wfile.write(body) -> request"""

from http.server import BaseHTTPRequestHandler

from mixinv2 import extern, public, resource


@extern
def request() -> BaseHTTPRequestHandler: ...


@extern
def body() -> bytes: ...


@public
@resource
def written(request: BaseHTTPRequestHandler, body: bytes) -> BaseHTTPRequestHandler:
    request.wfile.write(body)
    return request

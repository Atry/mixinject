"""send_response(status_code) + end_headers() + wfile.write(body) -> written"""

from http.server import BaseHTTPRequestHandler

from mixinv2 import extern, public, resource


@extern
def request() -> BaseHTTPRequestHandler: ...


@extern
def status_code() -> int: ...


@extern
def body() -> bytes: ...


@public
@resource
def written(
    request: BaseHTTPRequestHandler, status_code: int, body: bytes
) -> BaseHTTPRequestHandler:
    request.send_response(status_code)
    request.end_headers()
    request.wfile.write(body)
    return request

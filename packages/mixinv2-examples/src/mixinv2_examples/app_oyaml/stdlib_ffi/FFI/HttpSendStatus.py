"""request.send_response(status_code) -> request"""

from http.server import BaseHTTPRequestHandler

from mixinv2 import extern, public, resource


@extern
def request() -> BaseHTTPRequestHandler: ...


@extern
def status_code() -> int: ...


@public
@resource
def sent(request: BaseHTTPRequestHandler, status_code: int) -> BaseHTTPRequestHandler:
    request.send_response(status_code)
    return request

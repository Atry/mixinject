"""request.end_headers() -> request"""

from http.server import BaseHTTPRequestHandler

from mixinv2 import extern, public, resource


@extern
def request() -> BaseHTTPRequestHandler: ...


@public
@resource
def ended(request: BaseHTTPRequestHandler) -> BaseHTTPRequestHandler:
    request.end_headers()
    return request

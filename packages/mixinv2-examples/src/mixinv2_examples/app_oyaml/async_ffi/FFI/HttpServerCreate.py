"""Starlette app + uvicorn.Server"""

from collections.abc import Callable

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route

from mixinv2 import extern, public, resource


@extern
def host() -> str: ...


@extern
def port() -> int: ...


@extern
def handler_class() -> Callable: ...


@public
@resource
def server(host: str, port: int, handler_class: Callable) -> uvicorn.Server:
    application = Starlette(
        routes=[Route("/{path:path}", handler_class)],
    )
    configuration = uvicorn.Config(
        application, host=host, port=port, log_level="error",
    )
    return uvicorn.Server(configuration)

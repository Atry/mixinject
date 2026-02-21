"""Atomic stdlib wrappers (FFI) for the Overlay language web-app example.

Each @scope class wraps exactly ONE Python stdlib / built-in call.
All business logic (SQL queries, string formatting, routing, composition)
lives in .oyaml files — Python is only the FFI bridge.

Design rules:
  1. One @scope per stdlib call — no business logic.
  2. Every input is @extern — wired by oyaml.
  3. One @public @resource output per @scope.
"""

import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from overlay.language import extern, public, resource, scope


# ---- sqlite3 ----


@public
@scope
class SqliteConnect:
    """sqlite3.connect(database_path, check_same_thread=False)"""

    @extern
    def database_path() -> str: ...

    @public
    @resource
    def connection(database_path: str) -> sqlite3.Connection:
        return sqlite3.connect(database_path, check_same_thread=False)


@public
@scope
class SqliteExecuteScript:
    """connection.executescript(sql) → connection (returns same connection)"""

    @extern
    def connection() -> sqlite3.Connection: ...

    @extern
    def sql() -> str: ...

    @public
    @resource
    def executed(connection: sqlite3.Connection, sql: str) -> sqlite3.Connection:
        connection.executescript(sql)
        return connection


@public
@scope
class SqliteConnectAndExecuteScript:
    """sqlite3.connect(database_path) + executescript(setup_sql) → connection"""

    @extern
    def database_path() -> str: ...

    @extern
    def setup_sql() -> str: ...

    @public
    @resource
    def connection(database_path: str, setup_sql: str) -> sqlite3.Connection:
        conn = sqlite3.connect(database_path, check_same_thread=False)
        conn.executescript(setup_sql)
        return conn


@public
@scope
class SqliteScalarQuery:
    """connection.execute(sql).fetchall() → single scalar value"""

    @extern
    def connection() -> sqlite3.Connection: ...

    @extern
    def sql() -> str: ...

    @public
    @resource
    def scalar(connection: sqlite3.Connection, sql: str) -> object:
        row, = connection.execute(sql).fetchall()
        value, = row
        return value


@public
@scope
class SqliteRowQuery:
    """connection.execute(sql, parameters).fetchone() → single row"""

    @extern
    def connection() -> sqlite3.Connection: ...

    @extern
    def sql() -> str: ...

    @extern
    def parameters() -> tuple: ...

    @public
    @resource
    def row(connection: sqlite3.Connection, sql: str, parameters: tuple) -> tuple:
        result = connection.execute(sql, parameters).fetchone()
        assert result is not None, f"query returned no rows: {sql}"
        return result


# ---- tuple construction ----


@public
@scope
class TupleWrap:
    """(element,) → 1-tuple"""

    @extern
    def element() -> object: ...

    @public
    @resource
    def wrapped(element: object) -> tuple:
        return (element,)


# ---- tuple indexing ----


@public
@scope
class GetItem:
    """sequence[index] → element"""

    @extern
    def sequence() -> object: ...

    @extern
    def index() -> int: ...

    @public
    @resource
    def element(sequence: object, index: int) -> object:
        return sequence[index]  # type: ignore[index]



# ---- HTTP request extern ----


@public
@scope
class HttpRequestExtern:
    """Declares request as an extern — enables per-request injection via kwargs."""

    @extern
    def request() -> BaseHTTPRequestHandler: ...


# ---- Python object attribute access ----


@public
@scope
class GetPath:
    """request.path → str"""

    @extern
    def request() -> BaseHTTPRequestHandler: ...

    @public
    @resource
    def path(request: BaseHTTPRequestHandler) -> str:
        return request.path


# ---- domain-specific request handlers ----


@public
@scope
class ExtractUserId:
    """int(request.path.split(path_separator)[-1]) → user_id"""

    @extern
    def request() -> BaseHTTPRequestHandler: ...

    @extern
    def path_separator() -> str: ...

    @public
    @resource
    def user_id(request: BaseHTTPRequestHandler, path_separator: str) -> int:
        return int(request.path.split(path_separator)[-1])


@public
@scope
class FormatResponse:
    """template.format(total=user_count, current=current_user_name).encode() → response_body"""

    @extern
    def response_template() -> str: ...

    @extern
    def user_count() -> int: ...

    @extern
    def current_user_name() -> str: ...

    @public
    @resource
    def response_body(response_template: str, user_count: int, current_user_name: str) -> bytes:
        return response_template.format(total=user_count, current=current_user_name).encode()


# ---- string operations ----


@public
@scope
class StringSplit:
    """string.split(separator) → tuple of parts"""

    @extern
    def string() -> str: ...

    @extern
    def separator() -> str: ...

    @public
    @resource
    def parts(string: str, separator: str) -> tuple:
        return tuple(string.split(separator))


@public
@scope
class SequenceLast:
    """sequence[-1] → last element"""

    @extern
    def sequence() -> tuple: ...

    @public
    @resource
    def element(sequence: tuple) -> object:
        *_, last = sequence
        return last


@public
@scope
class IntParse:
    """int(string) → int"""

    @extern
    def string() -> str: ...

    @public
    @resource
    def value(string: str) -> int:
        return int(string)


@public
@scope
class StringFormatMap:
    """template.format_map(arguments) → str"""

    @extern
    def template() -> str: ...

    @extern
    def arguments() -> object: ...

    @public
    @resource
    def formatted(template: str, arguments: object) -> str:
        return template.format_map(arguments)


@public
@scope
class StringEncode:
    """string.encode() → bytes"""

    @extern
    def string() -> str: ...

    @public
    @resource
    def encoded(string: str) -> bytes:
        return string.encode()


# ---- HTTP response (chained: each returns request for ordering) ----


@public
@scope
class HttpSendStatus:
    """request.send_response(status_code) → request"""

    @extern
    def request() -> BaseHTTPRequestHandler: ...

    @extern
    def status_code() -> int: ...

    @public
    @resource
    def sent(request: BaseHTTPRequestHandler, status_code: int) -> BaseHTTPRequestHandler:
        request.send_response(status_code)
        return request


@public
@scope
class HttpEndHeaders:
    """request.end_headers() → request"""

    @extern
    def request() -> BaseHTTPRequestHandler: ...

    @public
    @resource
    def ended(request: BaseHTTPRequestHandler) -> BaseHTTPRequestHandler:
        request.end_headers()
        return request


@public
@scope
class HttpWriteBody:
    """request.wfile.write(body) → request"""

    @extern
    def request() -> BaseHTTPRequestHandler: ...

    @extern
    def body() -> bytes: ...

    @public
    @resource
    def written(request: BaseHTTPRequestHandler, body: bytes) -> BaseHTTPRequestHandler:
        request.wfile.write(body)
        return request


@public
@scope
class HttpSendResponse:
    """send_response(status_code) + end_headers() + wfile.write(body) → written"""

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


# ---- HTTP server ----


@public
@scope
class HttpHandlerClass:
    """Create a BaseHTTPRequestHandler subclass that dispatches GET to request_scope.response"""

    @scope
    def RequestScope() -> None: ...

    @public
    @resource
    def handler_class(RequestScope: Callable) -> type:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                RequestScope(request=self).response

            def log_message(self, format: str, *arguments: object) -> None:
                pass

        return Handler


@public
@scope
class HttpServerCreate:
    """HTTPServer((host, port), handler_class)"""

    @extern
    def host() -> str: ...

    @extern
    def port() -> int: ...

    @extern
    def handler_class() -> type: ...

    @public
    @resource
    def server(host: str, port: int, handler_class: type) -> HTTPServer:
        return HTTPServer((host, port), handler_class)

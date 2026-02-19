"""Runnable versions of all code examples shown in README.md.

Each test function mirrors a step in the README walkthrough so the examples
are guaranteed to be correct and up-to-date.

Examples use standard-library modules only:
- `sqlite3` for the database layer
- `http.server` for the HTTP layer
"""

import sqlite3
import threading
import urllib.request
from concurrent.futures import Future
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Iterator

from overlay.language import eager, extern, merge, patch, public, resource, scope
from overlay.language.runtime import evaluate


# ---------------------------------------------------------------------------
# Step 1 – Define services with @scope and @resource
# ---------------------------------------------------------------------------


class TestStep1BasicServices:
    """README Step 1: @scope, @resource, @public, @extern, evaluate()."""

    def test_extern_and_flat_composition(self) -> None:
        """@extern + multi-scope union-mount: each scope owns its own config."""

        @scope
        class SQLiteDatabase:
            @extern
            def database_path() -> str: ...

            @public
            @resource
            def connection(database_path: str) -> sqlite3.Connection:
                return sqlite3.connect(database_path)

        @scope
        class UserRepository:
            @public
            @resource
            def user_count(connection: sqlite3.Connection) -> int:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS users "
                    "(id INTEGER PRIMARY KEY, name TEXT)"
                )
                (count,) = connection.execute("SELECT COUNT(*) FROM users").fetchone()
                return count

        app = evaluate(SQLiteDatabase, UserRepository)
        root = app(database_path=":memory:")
        assert root.user_count == 0
        root.connection.close()


# ---------------------------------------------------------------------------
# Step 2 – Layer cross-cutting concerns with @patch and @merge
# ---------------------------------------------------------------------------


class TestStep2PatchAndMerge:
    """README Step 2: @patch applies a transformation; @merge sets aggregation."""

    def test_patch_overrides_resource(self) -> None:
        """A @patch wraps a @resource value with a transformation."""

        @scope
        class Base:
            @public
            @resource
            def max_connections() -> int:
                return 10

        @scope
        class HighLoad:
            """Patch for high-load environments: double the connection limit."""

            @patch
            def max_connections() -> Callable[[int], int]:
                return lambda previous: previous * 2

        root = evaluate(Base, HighLoad)
        assert root.max_connections == 20

    def test_merge_collects_patches_into_frozenset(self) -> None:
        """@merge defines the aggregation strategy for collected @patch values."""

        @scope
        class PragmaBase:
            @public
            @merge
            def startup_pragmas() -> Callable[[Iterator[str]], frozenset[str]]:
                return frozenset

        @scope
        class WalMode:
            @patch
            def startup_pragmas() -> str:
                return "PRAGMA journal_mode=WAL"

        @scope
        class ForeignKeys:
            @patch
            def startup_pragmas() -> str:
                return "PRAGMA foreign_keys=ON"

        root = evaluate(PragmaBase, WalMode, ForeignKeys)
        assert root.startup_pragmas == frozenset(
            {"PRAGMA journal_mode=WAL", "PRAGMA foreign_keys=ON"}
        )

    def test_patch_with_dependency_injection(self) -> None:
        """A @patch can itself declare @extern dependencies, provided as kwargs."""

        @scope
        class PragmaBase:
            @public
            @merge
            def startup_pragmas() -> Callable[[Iterator[str]], frozenset[str]]:
                return frozenset

        @scope
        class UserVersionPragma:
            @extern
            def schema_version() -> int: ...    # each scope owns its own config

            @patch
            def startup_pragmas(schema_version: int) -> str:
                return f"PRAGMA user_version={schema_version}"

        app = evaluate(PragmaBase, UserVersionPragma)
        root = app(schema_version=3)
        assert root.startup_pragmas == frozenset({"PRAGMA user_version=3"})


# ---------------------------------------------------------------------------
# Step 3 – @eager: force evaluation at startup
# ---------------------------------------------------------------------------


class TestStep3Eager:
    """README Step 3: @eager resources are evaluated immediately on scope creation."""

    def test_eager_runs_schema_migration_at_startup(self) -> None:
        """Schema migration runs immediately when evaluate() returns."""

        @scope
        class SQLiteDatabase:
            @public
            @eager
            @resource
            def connection() -> sqlite3.Connection:
                db = sqlite3.connect(":memory:")
                db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
                db.commit()
                return db

        # Schema migration already done by the time evaluate() returns
        root = evaluate(SQLiteDatabase)
        tables = root.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert ("users",) in tables
        root.connection.close()

    def test_lazy_connection_not_opened_until_accessed(self) -> None:
        opened: list[str] = []

        @scope
        class SQLiteDatabase:
            @public
            @resource  # no @eager
            def connection() -> sqlite3.Connection:
                opened.append("opened")
                return sqlite3.connect(":memory:")

        root = evaluate(SQLiteDatabase)
        assert opened == []  # connection not opened yet

        conn = root.connection
        assert opened == ["opened"]
        conn.close()


# ---------------------------------------------------------------------------
# Step 4 – App scope vs request scope: HTTP server with SQLite
#
# SQLiteDatabase owns its own config (database_path) and provides connection.
# AppServices declares @extern connection (its dependency on the DB layer),
# owns its own config (host, port), and contains RequestScope as a nested
# scope because request lifetime differs from app lifetime.
#
# Each scope declares only the @extern it needs — no shared Config scope.
# ---------------------------------------------------------------------------


class TestStep4HttpServer:
    """README Step 4: app scope vs request scope."""

    def test_app_and_request_scope(self) -> None:
        """Three scopes union-mounted flat; each owns its config.
        UserRepository is a @scope providing business-level resources.
        UserRepository.RequestScope provides per-request DB resources.
        AppServices.RequestScope extracts user_id from the HTTP request.
        The union-mount wires user_id → current_user automatically.
        """

        @scope
        class SQLiteDatabase:
            @extern
            def database_path() -> str: ...    # database owns its own config

            # App-scoped: one connection for the entire process lifetime.
            # check_same_thread=False: created in main thread, used in handler threads.
            @public
            @resource
            def connection(database_path: str) -> sqlite3.Connection:
                db = sqlite3.connect(database_path, check_same_thread=False)
                db.execute(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"
                )
                db.execute("INSERT INTO users VALUES (1, 'alice')")
                db.execute("INSERT INTO users VALUES (2, 'bob')")
                db.commit()
                return db

        @scope
        class UserRepository:
            @extern
            def connection() -> sqlite3.Connection: ...

            # @scope as a composable dataclass — fields are @extern, constructed via DI.
            @public
            @scope
            class User:
                @public
                @extern
                def user_id() -> int: ...

                @public
                @extern
                def name() -> str: ...

            # App-scoped: total count across all requests.
            @public
            @resource
            def user_count(connection: sqlite3.Connection) -> int:
                (count,) = connection.execute(
                    "SELECT COUNT(*) FROM users"
                ).fetchone()
                return count

            # Request-scoped: per-request DB resources, wired by overlay union-mount.
            @public
            @scope
            class RequestScope:
                @extern
                def user_id() -> int: ...  # provided by AppServices.RequestScope

                @public
                @resource
                def current_user(
                    connection: sqlite3.Connection, user_id: int, User: Callable
                ) -> object:
                    row = connection.execute(
                        "SELECT id, name FROM users WHERE id = ?", (user_id,)
                    ).fetchone()
                    assert row is not None, f"no user with id={user_id}"
                    identifier, name = row
                    return User(user_id=identifier, name=name)

        @scope
        class HttpHandlers:
            # RequestScope is nested because its lifetime is per-request,
            # not per-application.
            @public
            @scope
            class RequestScope:
                @extern
                def request() -> BaseHTTPRequestHandler: ...

                # user_id is extracted from the request and injected into
                # UserRepository.RequestScope.current_user automatically.
                @public
                @resource
                def user_id(request: BaseHTTPRequestHandler) -> int:
                    return int(request.path.split("/")[-1])

                @public
                @resource
                def response_body(user_count: int, current_user: object) -> bytes:
                    return (
                        f"total={user_count} current={current_user.name}"
                    ).encode()

                # IO resource: sends the HTTP response as a side effect.
                @public
                @resource
                def response_sent(
                    request: BaseHTTPRequestHandler,
                    response_body: bytes,
                ) -> None:
                    request.send_response(200)
                    request.end_headers()
                    request.wfile.write(response_body)

        @scope
        class NetworkServer:
            @extern
            def host() -> str: ...             # network layer owns its own config

            @extern
            def port() -> int: ...

            # RequestScope is injected by name as a Callable (StaticScope).
            # Calling RequestScope(request=handler) returns a fresh InstanceScope.
            @public
            @resource
            def server(host: str, port: int, RequestScope: Callable) -> HTTPServer:
                class Handler(BaseHTTPRequestHandler):
                    def do_GET(self) -> None:
                        RequestScope(request=self).response_sent

                    def log_message(self, format: str, *arguments: object) -> None:
                        pass

                return HTTPServer((host, port), Handler)

        # Each scope declares only its own config; all four are union-mounted flat.
        app = evaluate(SQLiteDatabase, UserRepository, HttpHandlers, NetworkServer)(
            database_path=":memory:",
            host="127.0.0.1",
            port=0,  # OS assigns a free port
        )

        server = app.server
        server_thread = threading.Thread(target=server.handle_request, daemon=True)
        server_thread.start()

        assigned_port = server.server_address[1]
        response = urllib.request.urlopen(
            f"http://127.0.0.1:{assigned_port}/users/1"
        )
        assert response.read() == b"total=2 current=alice"

        server_thread.join(timeout=2)
        server.server_close()
        app.connection.close()

    def test_request_scope_created_fresh_per_request(self) -> None:
        """Each call to RequestScope(...) produces an independent InstanceScope."""

        @scope
        class AppServices:
            @public
            @scope
            class RequestScope:
                @extern
                def request_id() -> int: ...

                @public
                @resource
                def label(request_id: int) -> str:
                    return f"request-{request_id}"

        app = evaluate(AppServices)

        scope_a = app.RequestScope(request_id=1)
        scope_b = app.RequestScope(request_id=2)

        assert scope_a.label == "request-1"
        assert scope_b.label == "request-2"

    def test_write_operation_via_future_injection(self) -> None:
        """Write operations: inject a Future at call time; the resource resolves it."""

        @dataclass
        class User:
            user_id: int
            name: str

        @scope
        class SQLiteDatabase:
            @extern
            def database_path() -> str: ...

            @public
            @resource
            def connection(database_path: str) -> sqlite3.Connection:
                db = sqlite3.connect(database_path, check_same_thread=False)
                db.execute(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"
                )
                db.commit()
                return db

        @scope
        class UserRepository:
            @extern
            def connection() -> sqlite3.Connection: ...

            @public
            @resource
            def user_count(connection: sqlite3.Connection) -> int:
                (count,) = connection.execute(
                    "SELECT COUNT(*) FROM users"
                ).fetchone()
                return count

            @public
            @scope
            class RequestScope:
                # Caller creates a Future and passes it in; this resource resolves it.
                @extern
                def user_created_future() -> "Future[User]": ...

                @public
                @resource
                def user_created(
                    connection: sqlite3.Connection,
                    user_created_future: "Future[User]",
                ) -> None:
                    cursor = connection.execute(
                        "INSERT INTO users (name) VALUES (?)", ("alice",)
                    )
                    connection.commit()
                    user_created_future.set_result(
                        User(user_id=cursor.lastrowid, name="alice")
                    )

        app = evaluate(SQLiteDatabase, UserRepository)(
            database_path=":memory:",
        )

        # Write: caller creates the Future, injects it, accesses the resource.
        future: Future[User] = Future()
        request_scope = app.RequestScope(user_created_future=future)
        request_scope.user_created  # triggers the insert and resolves the future

        new_user = future.result()
        assert new_user == User(user_id=1, name="alice")
        assert app.user_count == 1  # app-scoped count is still cached from before insert

        app.connection.close()

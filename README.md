# Overlay Language

A pytest-fixture-inspired dependency injection framework for Python.

Declare your services, wire their dependencies through parameter names — just like
pytest fixtures — then compose them at the call site.

```
pip install overlay.language
```

---

## Python API

The examples below build a single web application step by step, introducing one
concept at a time. All code is runnable with the standard library only.

### Step 1 — Define services

Decorate a class with `@scope` to make it a DI container. Annotate each value with
`@resource` and expose it with `@public`. Resources declare their dependencies as
ordinary function parameters; the framework injects them by name.

Use `@extern` to declare a dependency that must come from outside the scope — the
equivalent of a pytest fixture parameter. Pass multiple scopes to `evaluate()` to
compose them; dependencies are resolved by name across scope boundaries. Config
values are passed as kwargs when calling the evaluated scope.

```python
import sqlite3
from overlay.language import extern, public, resource, scope
from overlay.language.runtime import evaluate

@scope
class SQLiteDatabase:
    @extern
    def database_path() -> str: ...       # caller must provide this

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
            "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)"
        )
        (count,) = connection.execute("SELECT COUNT(*) FROM users").fetchone()
        return count

app = evaluate(SQLiteDatabase, UserRepository)
root = app(database_path=":memory:")
assert root.user_count == 0
```

`SQLiteDatabase` owns `database_path`; `UserRepository` has no knowledge of the
database layer — it only declares `connection: sqlite3.Connection` as a parameter
and receives it automatically from the composed scope.

### Step 2 — Layer cross-cutting concerns with `@patch` and `@merge`

`@patch` wraps an existing resource value with a transformation. This lets an
add-on scope modify a value without touching the scope that defined it — the same
idea as pytest's `monkeypatch`, but composable.

```python
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
assert root.max_connections == 20         # 10 * 2
```

When several independent scopes each contribute a piece to the same resource, use
`@merge` to define how the contributions are aggregated:

```python
@scope
class PragmaBase:
    @public
    @merge
    def startup_pragmas() -> Callable[[Iterator[str]], frozenset[str]]:
        return frozenset                  # aggregation strategy: collect into frozenset

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
```

A `@patch` can itself declare `@extern` dependencies, which are injected like any
other resource:

```python
@scope
class PragmaBase:
    @public
    @merge
    def startup_pragmas() -> Callable[[Iterator[str]], frozenset[str]]:
        return frozenset

@scope
class UserVersionPragma:
    @extern
    def schema_version() -> int: ...     # provided as a kwarg at call time

    @patch
    def startup_pragmas(schema_version: int) -> str:
        return f"PRAGMA user_version={schema_version}"

app = evaluate(PragmaBase, UserVersionPragma)
root = app(schema_version=3)
assert root.startup_pragmas == frozenset({"PRAGMA user_version=3"})
```

### Step 3 — Force evaluation at startup with `@eager`

All resources are lazy by default: computed on first access, then cached for the
lifetime of the scope. Mark a resource `@eager` to evaluate it immediately when
`evaluate()` returns — useful for schema migrations or connection pre-warming that
must complete before the application starts serving requests:

```python
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
```

Without `@eager`, the `CREATE TABLE` would not run until `root.connection` is first
accessed.

### Step 4 — App scope vs request scope

So far all resources have had application lifetime: created once at startup and
reused for every request. Real applications also need per-request resources — values
that must be created fresh for each incoming request and discarded when it completes.

A nested `@scope` named `RequestScope` serves as a per-request factory. The
framework injects it by name as a `Callable`; calling
`RequestScope(request=handler)` returns a fresh instance.

The application below has four scopes, each owning only its own concern:

- **`SQLiteDatabase`** — owns `database_path`, provides `connection`
- **`UserRepository`** — business logic; owns `user_count` and per-request `current_user`
- **`HttpHandlers`** — HTTP layer; owns per-request `user_id`, `response_body`, `response_sent`
- **`NetworkServer`** — network layer; owns `host`/`port`, creates the `HTTPServer`

`UserRepository.RequestScope` and `HttpHandlers.RequestScope` are composed into a
single `RequestScope` by the union mount. `user_id` (extracted from the HTTP path
by `HttpHandlers.RequestScope`) flows automatically into `current_user` (looked up
in the DB by `UserRepository.RequestScope`) without any glue code.

`response_sent` is an IO resource: it sends the HTTP response as a side effect and
returns `None`. The handler body is a single attribute access — all logic lives in
the DI graph. In an async framework (e.g. FastAPI), return an `asyncio.Task[None]`
instead of a coroutine, which cannot be safely awaited in multiple dependents.

```python
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

@scope
class SQLiteDatabase:
    @extern
    def database_path() -> str: ...      # database owns its own config

    # App-scoped: one connection for the entire process lifetime.
    # check_same_thread=False: created in main thread, used in handler threads.
    @public
    @resource
    def connection(database_path: str) -> sqlite3.Connection:
        db = sqlite3.connect(database_path, check_same_thread=False)
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
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

    # App-scoped: total count, computed once.
    @public
    @resource
    def user_count(connection: sqlite3.Connection) -> int:
        (count,) = connection.execute("SELECT COUNT(*) FROM users").fetchone()
        return count

    # Request-scoped: per-request DB resources.
    @public
    @scope
    class RequestScope:
        @extern
        def user_id() -> int: ...        # provided by HttpHandlers.RequestScope

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

        # current_user and user_count resolved from their respective scopes.
        @public
        @resource
        def response_body(user_count: int, current_user: object) -> bytes:
            return f"total={user_count} current={current_user.name}".encode()

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
    def host() -> str: ...               # network layer owns its own config

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

        return HTTPServer((host, port), Handler)

# Four scopes union-mounted flat; each declares only its own config.
app = evaluate(SQLiteDatabase, UserRepository, HttpHandlers, NetworkServer)(
    database_path="/var/lib/myapp/prod.db",
    host="127.0.0.1",
    port=8080,
)
server = app.server
```

Swapping to a test configuration is just different kwargs; no scope changes:

```python
test_app = evaluate(SQLiteDatabase, UserRepository, HttpHandlers, NetworkServer)(
    database_path=":memory:",  # fresh, isolated database for each test
    host="127.0.0.1",
    port=0,                    # OS assigns a free port
)
# test_app.connection  → sqlite3.Connection to :memory:
# test_app.server      → HTTPServer on OS-assigned port
```

---

## Decorator reference

| Decorator | Purpose |
|-----------|---------|
| `@scope` | Define a DI container (class) or sub-namespace |
| `@resource` | Declare a lazily-computed value; parameters are injected by name |
| `@public` | Expose a `@resource` or `@scope` to external callers |
| `@extern` | Declare a required dependency that must come from the composed scope |
| `@patch` | Provide a transformation that wraps an existing resource |
| `@patch_many` | Like `@patch` but yields multiple transformations at once |
| `@merge` | Define how patches are aggregated (e.g. `frozenset`, `list`, custom reducer) |
| `@eager` | Force evaluation at scope creation rather than on first access |
| `@extend(*refs)` | Inherit from other scopes explicitly (for package-level union mounts) |
| `evaluate(*scopes)` | Resolve and union-mount one or more scopes into a single dependency graph |

---

## Python modules as scopes

Every `@scope`-decorated class in the examples above can be replaced by a plain
Python module or package file. Pass a module directly to `evaluate()`:

```python
import sqlite_database   # sqlite_database.py with @extern / @resource / @public
import user_repository   # user_repository/ package

app = evaluate(sqlite_database, user_repository, modules_public=True)(
    database_path=":memory:",
)
```

The same decorators (`@resource`, `@extern`, `@patch`, `@merge`, `@eager`,
`@public`) work on module-level functions exactly as on class methods. A
subpackage becomes a nested scope — `user_repository/request_scope/` is the
module equivalent of a nested `@scope class RequestScope`.

Use `@extend` in a package's `__init__.py` to pre-wire the union mount so
callers pass just one argument to `evaluate()` instead of listing every module.

Runnable module-based equivalents of all README examples are in
[tests/test_readme_package_examples.py](tests/test_readme_package_examples.py),
using the fixture package at [tests/fixtures/app_di/](tests/fixtures/app_di/).

---

## Overlay language

For large projects it can be more convenient to declare scopes in `.oyaml` files
rather than Python classes. The Overlay language is a YAML-based configuration
language with mixin composition, lazy evaluation, and lexical scoping — essentially
the same dependency-injection semantics as the Python API, but expressed as data.

```yaml
# sqlite_database.oyaml
SQLiteDatabase:
  database_path: []        # abstract slot — value provided at compose time
  connection:
    database_path: [database_path]

# app.oyaml — union-mounts SQLiteDatabase and UserRepository
- [SQLiteDatabase]
- UserRepository:
    user_count:
      connection: [connection]
```

The full language specification is in [specification.md](specification.md).

The semantics of the Overlay language are grounded in the
[Overlay Calculus](https://arxiv.org/abs/2602.16291), a formal calculus for
mixin composition.

---

## Installation

```
pip install overlay.language
```

PyPI: <https://pypi.org/project/overlay.language/>

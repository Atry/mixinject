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
from types import ModuleType

from overlay.language import RelativeReference as R, extend

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

# Declare composition via @extend — each scope only knows its own config.
@extend(
    R(de_bruijn_index=0, path=("SQLiteDatabase",)),
    R(de_bruijn_index=0, path=("UserRepository",)),
    R(de_bruijn_index=0, path=("HttpHandlers",)),
    R(de_bruijn_index=0, path=("NetworkServer",)),
)
@public
@scope
class app:
    pass

# Assemble into a module and evaluate — composition is declared above, not here.
myapp = ModuleType("myapp")
myapp.SQLiteDatabase = SQLiteDatabase
myapp.UserRepository = UserRepository
myapp.HttpHandlers = HttpHandlers
myapp.NetworkServer = NetworkServer
myapp.app = app

root = evaluate(myapp, modules_public=True).app(
    database_path="/var/lib/myapp/prod.db",
    host="127.0.0.1",
    port=8080,
)
server = root.server
```

Swapping to a test configuration is just different kwargs; no scope or composition changes:

```python
test_root = evaluate(myapp, modules_public=True).app(
    database_path=":memory:",  # fresh, isolated database for each test
    host="127.0.0.1",
    port=0,                    # OS assigns a free port
)
# test_root.connection  → sqlite3.Connection to :memory:
# test_root.server      → HTTPServer on OS-assigned port
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

The `@scope` classes above are a teaching convenience — the real-world style is
plain Python modules, just like pytest fixtures don't require a class. Every
`@scope` class maps directly to a module file; pass it to `evaluate()` the same
way:

```python
import sqlite_database   # sqlite_database.py with @extern / @resource / @public
import user_repository   # user_repository/ package
```

The same decorators work on module-level functions exactly as on class methods. A
subpackage becomes a nested scope — `user_repository/request_scope/` is the
module equivalent of a nested `@scope class RequestScope`.

Use `@extend` in a package's `__init__.py` to declare the composition, then
`evaluate()` receives the single package:

```python
# myapp/__init__.py
from overlay.language import RelativeReference as R, extend, public, scope

@extend(
    R(de_bruijn_index=0, path=("sqlite_database",)),
    R(de_bruijn_index=0, path=("user_repository",)),
)
@public
@scope
class app:
    pass
```

```python
import myapp

root = evaluate(myapp, modules_public=True).app(database_path=":memory:")
```

Runnable module-based equivalents of all README examples are in
[tests/test_readme_package_examples.py](tests/test_readme_package_examples.py),
using the fixture package at [tests/fixtures/app_di/](tests/fixtures/app_di/).

---

## Overlay language

The Step 4 Python code works, but it has a structural problem: **business logic
and I/O are tangled together**. Consider `user_id` in `HttpHandlers`:

```python
def user_id(request: BaseHTTPRequestHandler) -> int:
    return int(request.path.split("/")[-1])
```

This one function mixes three concerns: reading `request.path` (I/O), splitting
on `"/"` (a business decision about URL format), and parsing the last segment as
an integer (another business decision). The path separator, SQL queries, and
format templates are all hardcoded in Python — changing any of them means
changing Python code.

The Overlay language solves this by separating the application into three layers:

- **Python FFI** wraps individual stdlib calls in `@scope` adapters — one class
  per operation (`sqlite3.connect`, `str.split`, `wfile.write`). Each adapter
  declares its inputs as `@extern` and exposes a single `@public @resource`
  output. The adapter contains **zero business logic**.
- **`.oyaml` files** contain all application logic. Overlay is not just a
  configuration format — it is a complete language with lexical scoping, nested
  scopes, deep-merge composition, and lazy evaluation. These features make it
  more natural than Python for expressing business logic, which is inherently
  declarative ("the user ID is the last URL segment", "the response format is
  `total={total} current={current}`").
- **Configuration values** (SQL queries, format strings, host/port) are pure
  YAML scalars, gathered in one place.

Business logic written in `.oyaml` is **portable**: it is decoupled from the
Python FFI layer. Swap the FFI adapters and the same `.oyaml` logic runs against
a different runtime — mock adapters for unit testing, a different language's
stdlib for cross-platform deployment, or instrumented adapters for profiling.
With Python `@scope` decorators, business logic is locked to the Python runtime
and cannot be extracted or retargeted.

Below is the same Step 4 web application rewritten in this style.

### Python FFI adapters

Each `@scope` class wraps exactly one stdlib operation. Below are three
representative adapters; the full module
([tests/fixtures/app_oyaml/stdlib_ffi/FFI.py](tests/fixtures/app_oyaml/stdlib_ffi/FFI.py))
contains 10 more following the same pattern.

```python
# stdlib_ffi/FFI.py — each @scope wraps ONE stdlib call
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from overlay.language import extern, public, resource, scope

@public
@scope
class SqliteConnectAndExecuteScript:
    """Multiple inputs → single output"""
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
class GetItem:
    """Generic operation: sequence[index] → element"""
    @extern
    def sequence() -> object: ...

    @extern
    def index() -> int: ...

    @public
    @resource
    def element(sequence: object, index: int) -> object:
        return sequence[index]

@public
@scope
class HttpSendResponse:
    """Chained I/O: send status + headers + body → request handle"""
    @extern
    def request() -> BaseHTTPRequestHandler: ...

    @extern
    def status_code() -> int: ...

    @extern
    def body() -> bytes: ...

    @public
    @resource
    def written(
        request: BaseHTTPRequestHandler, status_code: int, body: bytes,
    ) -> BaseHTTPRequestHandler:
        request.send_response(status_code)
        request.end_headers()
        request.wfile.write(body)
        return request
```

Notice what is *not* here: no SQL queries, no `"/"` separator, no format string,
no `:memory:` path, no port number. Those are all business decisions that live
in the `.oyaml`.

### `.oyaml` composition

An `.oyaml` file describes a **dependency graph**, not an execution sequence.
There is no top-to-bottom control flow — the runtime evaluates resources lazily,
on demand. Think spreadsheet cells, not shell scripts.

The business logic lives in `Library.oyaml`, which references FFI adapters
through abstract declarations (`FFI:` scope with `[]` slots). A concrete FFI
module (`stdlib_ffi/FFI.py`) overrides these slots at composition time. This
separation means the business logic is portable — swap `stdlib_ffi` for a
different FFI implementation and the `.oyaml` files need no changes.

The following sections walk through `Library.oyaml` one scope at a time,
introducing new language concepts as they appear.

#### `SQLiteDatabase` — extern, inheritance, wiring, projection

```yaml
SQLiteDatabase:
  database_path: []                         # extern: caller must provide this
  setup_sql: []                             # extern: caller must provide this
  _db:
    - [FFI, SqliteConnectAndExecuteScript]  # inherit the FFI adapter
    - database_path: [database_path]        # wire extern → adapter input
      setup_sql: [setup_sql]
  connection: [_db, connection]             # projection: expose _db.connection
```

Four new concepts:

- **`field: []`** — an **extern declaration**, the `.oyaml` equivalent of
  `@extern`. The value must come from a parent scope or the caller.
- **`- [FFI, SqliteConnectAndExecuteScript]`** — **inheritance**. `_db` inherits
  the FFI adapter, gaining all of its resources (`connection`).
- **`database_path: [database_path]`** — **wiring**. The reference `[database_path]`
  is a lexical lookup: search outward through enclosing scopes until a field
  named `database_path` is found.
- **`connection: [_db, connection]`** — **path navigation**. Access the
  `connection` resource on the child scope `_db`. The leading underscore on
  `_db` makes it private; `connection` is the public-facing projection.

#### `UserRepository` (app-scoped part) — nested scope, scope-as-dataclass

```yaml
UserRepository:
  connection: []                            # extern: from SQLiteDatabase
  user_count_sql: []                        # extern: provided by app

  User:                                     # scope-as-dataclass
    user_id: []
    name: []

  _count:
    - [FFI, SqliteScalarQuery]
    - connection: [connection]
      sql: [user_count_sql]
  user_count: [_count, scalar]
```

- **`User:`** is a **nested scope** with two extern fields — the `.oyaml`
  equivalent of `@scope class User` with `@public @extern` fields. It acts as a
  dataclass constructor: `current_user` (below) will supply values for
  `user_id` and `name`.
- **`connection: []`** declares that `UserRepository` expects a `connection`
  from outside. When composed with `SQLiteDatabase` inside `app`, this extern
  is satisfied by `SQLiteDatabase.connection` — resolved by name through
  lexical scoping.

#### `UserRepository.RequestScope` — ANF style, cross-scope references

```yaml
  RequestScope:
    user_id: []                             # extern: from HttpHandlers
    user_query_sql: []                      # extern: from app.RequestScope

    _params:
      - [FFI, TupleWrap]
      - element: [user_id]

    _row:
      - [FFI, SqliteRowQuery]
      - connection: [connection]            # lexical: finds UserRepository.connection
        sql: [user_query_sql]
        parameters: [_params, wrapped]

    _identifier:
      - [FFI, GetItem]
      - sequence: [_row, row]
        index: 0
    _name:
      - [FFI, GetItem]
      - sequence: [_row, row]
        index: 1

    current_user:
      user_id: [_identifier, element]
      name: [_name, element]

    current_user_name: [current_user, name]
```

This section demonstrates **A-Normal Form (ANF)**: every intermediate result
must be bound to a named field. You cannot write
`GetItem(sequence=SqliteRowQuery(...).row, index=0)` — instead, `_row` holds
the query result, and `_identifier` extracts column 0 from `_row.row`. The
cost is verbosity; the benefit is that every intermediate value is inspectable
and independently composable.

**Cross-scope lexical reference:** `connection: [connection]` inside
`RequestScope` finds `UserRepository.connection` — the lexical scope chain
searches outward through parent, grandparent, etc. No import statement is
needed; the scope hierarchy *is* the namespace.

**Constructing `current_user`:** Instead of calling `User(user_id=..., name=...)`,
the `.oyaml` directly defines `current_user` as a scope with two fields. The
`User` scope-as-dataclass above establishes the field names; here those same
names are filled with concrete values.

#### `HttpHandlers` — flat inheritance, qualified this

```yaml
HttpHandlers:
  user_count: []                            # extern: from UserRepository

  RequestScope:
    - [FFI, ExtractUserId]                  # provides: user_id
    - [FFI, HttpSendResponse]              # provides: written
    - request: []                           # extern: injected per-request
      path_separator: []                    # extern: from app.RequestScope
      response_template: []                 # extern: from app.RequestScope
      status_code: 200                      # inline scalar
      current_user_name: []                 # extern: from UserRepository.RequestScope

      _format:
        - [FFI, FormatResponse]
        - response_template: [response_template]
          user_count: [user_count]
          current_user_name: [current_user_name]
      response_body: [_format, response_body]
      body: [response_body]

      response: [RequestScope, ~, written]
```

**Flat inheritance:** `RequestScope` inherits *two* FFI adapters in its
inheritance list (`- [FFI, ExtractUserId]`, `- [FFI, HttpSendResponse]`). Their
`@extern` and `@resource` fields all merge into `RequestScope`'s own field
namespace. The last list item (the mapping starting with `request: []`) defines
`RequestScope`'s own fields.

**Lexical scoping across scope boundaries:** `[user_count]` inside
`RequestScope` searches outward and finds `HttpHandlers.user_count`. At this
point `user_count` is just an extern `[]` — its actual value comes from
`UserRepository` after deep merge (explained below).

**Qualified this: `[RequestScope, ~, written]`** — instead of declaring
`written: []` and writing `response: [written]`, this navigates the runtime
composition graph to access the `written` property inherited from
`HttpSendResponse`. The advantage: if `HttpSendResponse` is accidentally not
composed, this fails with an error instead of silently creating an empty scope.

#### `NetworkServer` — deep merge, config scoping

```yaml
NetworkServer:
  - [FFI, HttpServerCreate]
  - host: []
    port: []
    RequestScope: []
    _handler:
      - [FFI, HttpHandlerClass]
      - RequestScope: [RequestScope]
    handler_class: [_handler, handler_class]
```

All the scopes above live in `Library.oyaml`. They reference `[FFI, Xxx]` which
resolves to abstract declarations at the top of the file — no concrete Python
code is involved yet.

#### `Apps.oyaml` — integration entry point

`Apps.oyaml` is a separate file that inherits the real FFI implementation and
the Library, then defines concrete application entries:

```yaml
# Apps.oyaml
- [stdlib_ffi]                          # inherit real Python FFI adapters
- [Library]                             # inherit business logic
- memory_app:
    - [Apps, ~, SQLiteDatabase]         # qualified this: inherited from Library
    - [Apps, ~, UserRepository]
    - [Apps, ~, HttpHandlers]
    - [Apps, ~, NetworkServer]
    - database_path: ":memory:"
      setup_sql: |
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO users VALUES (1, 'alice');
        INSERT INTO users VALUES (2, 'bob');
      user_count_sql: "SELECT COUNT(*) FROM users"
      host: "127.0.0.1"
      port: 0
      RequestScope:
        user_query_sql: "SELECT id, name FROM users WHERE id = ?"
        path_separator: "/"
        response_template: "total={total} current={current}"
```

**Library/FFI separation:** `- [stdlib_ffi]` makes the real `FFI` module
(Python `@scope` classes) visible. `- [Library]` makes the business logic
visible. When composed, `stdlib_ffi.FFI` (real implementations) deep-merges
with `Library.FFI` (abstract declarations), and the real `@resource` methods
override the `[]` slots. The business logic never imports Python directly.

**Portability:** To run the same business logic on a different runtime, replace
`- [stdlib_ffi]` with a different FFI package — the `Library.oyaml` file needs
no changes. To test with mocks, provide a mock FFI module instead of
`stdlib_ffi`.

**["What Color Is Your Function?"](https://journal.stuffwithstuff.com/2015/02/01/what-color-is-your-function/):**
The same `Library.oyaml` runs unchanged on both synchronous and asynchronous
runtimes. Replacing `- [stdlib_ffi]` with `- [async_ffi]` swaps the FFI layer
to one built on `aiosqlite` + `starlette`
([implementation](tests/fixtures/app_oyaml/async_ffi/FFI/)) — the business
logic never knows whether it is sync or async. Function colour is confined
entirely to the FFI boundary; `Library.oyaml` itself is *colourless*.

**Composition via inheritance:** `memory_app` inherits four scopes via
qualified this (`[Apps, ~, SQLiteDatabase]` etc.) because these scopes are
inherited properties, not own properties of `Apps.oyaml`. This is not four
separate instances — it is a single scope with all four merged together. The
last list item supplies concrete values for every `[]` extern.

**Deep merge:** Both `UserRepository` and `HttpHandlers` define a
`RequestScope`. When composed inside `memory_app`, these merge by name into a
single `RequestScope`. After merging:

- `user_id` (from `HttpHandlers.RequestScope` via `ExtractUserId`) becomes
  visible to `UserRepository.RequestScope`, which uses it to look up
  `current_user`
- `current_user_name` (from `UserRepository.RequestScope`) becomes visible to
  `HttpHandlers.RequestScope`, which uses it in `_format`

Neither scope imports or references the other — deep merge makes their fields
mutual siblings automatically. This is the most powerful feature of the Overlay
language: cross-cutting concerns compose without glue code.

**Config value scoping:** App-lifetime values (`database_path`, `host`, `port`)
live directly in `memory_app`. Request-lifetime values (`user_query_sql`,
`path_separator`, `response_template`) live in `memory_app.RequestScope` — they
are only needed during request handling.

#### Syntax quick reference

| Syntax | Meaning |
|--------|---------|
| `field: []` | **Extern** — value must be provided by a parent scope or caller |
| `field: [other]` | **Lexical reference** — look up `other` in the lexical scope chain |
| `field: [child, property]` | **Path navigation** — access `property` on `child` |
| `field: [Scope, ~, symbol]` | **Qualified this** — access inherited `symbol` through the runtime graph |
| `field: "literal"` | **Scalar value** — string, number, etc. |
| `_field: ...` | **Private** — not visible to external callers (leading underscore) |
| `Scope:` with a mapping | **Nested scope** — a child scope with its own fields |
| `Scope:` with a list | **Inheritance** — `- [Parent]` items are inherited scopes; the last item (a mapping) defines own fields |

#### Python vs Overlay language

| Aspect | Python `@scope` | `.oyaml` |
|--------|-----------------|----------|
| Composition | Manual `@extend` + `RelativeReference` | Inheritance list: `- [Parent]` |
| Dependency injection | `@extern` parameter names | `field: []` + lexical scope chain |
| Expression style | Nested function calls | ANF: every intermediate has a name |
| Cross-cutting concerns | Explicit adapter / glue code | Deep merge: same-named scopes auto-merge |
| Accessing inherited members | `self.xxx` / parameter injection | Qualified this: `[Scope, ~, symbol]` |
| Business logic location | Mixed with I/O in Python | Separate `.oyaml` file, portable across FFI |
| Configuration | Kwargs at call site | Scalar values in `memory_app:` scope |

### Evaluation

```python
import tests.fixtures.app_oyaml as app_oyaml
from overlay.language.runtime import evaluate

# evaluate() auto-discovers stdlib_ffi/, Library.oyaml, and Apps.oyaml.
root = evaluate(app_oyaml, modules_public=True)

# Access the composed app — Apps is the .oyaml file name.
composed_app = root.Apps.memory_app

composed_app.server               # HTTPServer on 127.0.0.1:<assigned port>
composed_app.connection           # sqlite3.Connection to :memory:
composed_app.user_count           # 2

# Create a fresh request scope (per-request resources):
scope = composed_app.RequestScope(request=fake_request)
scope.current_user.name           # "alice"
scope.response                    # sends HTTP response as side effect
```

Swapping configuration is just a different entry in `Apps.oyaml` — the Python
FFI adapters and `Library.oyaml` never change. Swapping the FFI layer is just a
different `@scope` module — the `.oyaml` business logic never changes.

Runnable tests for this example are in
[tests/test_readme_package_examples.py](tests/test_readme_package_examples.py),
using the fixture package at [tests/fixtures/app_oyaml/](tests/fixtures/app_oyaml/).

The full language specification is in [specification.md](specification.md).

The semantics of the Overlay language are grounded in the
[Overlay Calculus](https://arxiv.org/abs/2602.16291), a formal calculus for
overlays.

---

## Installation

```
pip install overlay.language
```

PyPI: <https://pypi.org/project/overlay.language/>

Getting Started with Decorators
================================

The examples below build a single web application step by step, introducing one
concept at a time. All code is runnable with the standard library only.


Step 1 — Define services
------------------------

Decorate a class with ``@scope`` to make it a DI container. Annotate each value with
``@resource`` and expose it with ``@public``. Resources declare their dependencies as
ordinary function parameters; the framework injects them by name.

Use ``@extern`` to declare a dependency that must come from outside the scope — the
equivalent of a pytest fixture parameter. Pass multiple scopes to ``evaluate()`` to
compose them; dependencies are resolved by name across scope boundaries. Config
values are passed as kwargs when calling the evaluated scope.

.. literalinclude:: ../../tests/test_readme_examples.py
   :language: python
   :start-after: # [docs:step1-define-services]
   :end-before: # [/docs:step1-define-services]
   :dedent:

``SQLiteDatabase`` owns ``database_path``; ``UserRepository`` has no knowledge of the
database layer — it only declares ``connection: sqlite3.Connection`` as a parameter
and receives it automatically from the composed scope.


Step 2 — Layer cross-cutting concerns with ``@patch`` and ``@merge``
--------------------------------------------------------------------

``@patch`` wraps an existing resource value with a transformation. This lets an
add-on scope modify a value without touching the scope that defined it — the same
idea as pytest's ``monkeypatch``, but composable.

.. literalinclude:: ../../tests/test_readme_examples.py
   :language: python
   :start-after: # [docs:step2-patch]
   :end-before: # [/docs:step2-patch]
   :dedent:

When several independent scopes each contribute a piece to the same resource, use
``@merge`` to define how the contributions are aggregated:

.. literalinclude:: ../../tests/test_readme_examples.py
   :language: python
   :start-after: # [docs:step2-merge]
   :end-before: # [/docs:step2-merge]
   :dedent:

A ``@patch`` can itself declare ``@extern`` dependencies, which are injected like any
other resource:

.. literalinclude:: ../../tests/test_readme_examples.py
   :language: python
   :start-after: # [docs:step2-patch-extern]
   :end-before: # [/docs:step2-patch-extern]
   :dedent:


Step 3 — Force evaluation at startup with ``@eager``
-----------------------------------------------------

All resources are lazy by default: computed on first access, then cached for the
lifetime of the scope. Mark a resource ``@eager`` to evaluate it immediately when
``evaluate()`` returns — useful for schema migrations or connection pre-warming that
must complete before the application starts serving requests:

.. literalinclude:: ../../tests/test_readme_examples.py
   :language: python
   :start-after: # [docs:step3-eager]
   :end-before: # [/docs:step3-eager]
   :dedent:

Without ``@eager``, the ``CREATE TABLE`` would not run until ``root.connection`` is first
accessed.


Step 4 — App scope vs request scope
------------------------------------

So far all resources have had application lifetime: created once at startup and
reused for every request. Real applications also need per-request resources — values
that must be created fresh for each incoming request and discarded when it completes.

A nested ``@scope`` named ``RequestScope`` serves as a per-request factory. The
framework injects it by name as a ``Callable``; calling
``RequestScope(request=handler)`` returns a fresh instance.

The application below has four scopes, each owning only its own concern:

- **SQLiteDatabase** — owns ``database_path``, provides ``connection``
- **UserRepository** — business logic; owns ``user_count`` and per-request ``current_user``
- **HttpHandlers** — HTTP layer; owns per-request ``user_id``, ``response_body``, ``response_sent``
- **NetworkServer** — network layer; owns ``host``/``port``, creates the ``HTTPServer``

``UserRepository.RequestScope`` and ``HttpHandlers.RequestScope`` are composed into a
single ``RequestScope`` by the union mount. ``user_id`` (extracted from the HTTP path
by ``HttpHandlers.RequestScope``) flows automatically into ``current_user`` (looked up
in the DB by ``UserRepository.RequestScope``) without any glue code.

``response_sent`` is an IO resource: it sends the HTTP response as a side effect and
returns ``None``. The handler body is a single attribute access — all logic lives in
the DI graph. In an async framework (e.g. FastAPI), return an ``asyncio.Task[None]``
instead of a coroutine, which cannot be safely awaited in multiple dependents.

.. code-block:: python

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

Swapping to a test configuration is just different kwargs; no scope or composition changes:

.. code-block:: python

   test_root = evaluate(myapp, modules_public=True).app(
       database_path=":memory:",  # fresh, isolated database for each test
       host="127.0.0.1",
       port=0,                    # OS assigns a free port
   )
   # test_root.connection  → sqlite3.Connection to :memory:
   # test_root.server      → HTTPServer on OS-assigned port


Decorator reference
-------------------

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Decorator
     - Purpose
   * - ``@scope``
     - Define a DI container (class) or sub-namespace
   * - ``@resource``
     - Declare a lazily-computed value; parameters are injected by name
   * - ``@public``
     - Expose a ``@resource`` or ``@scope`` to external callers
   * - ``@extern``
     - Declare a required dependency that must come from the composed scope
   * - ``@patch``
     - Provide a transformation that wraps an existing resource
   * - ``@patch_many``
     - Like ``@patch`` but yields multiple transformations at once
   * - ``@merge``
     - Define how patches are aggregated (e.g. ``frozenset``, ``list``, custom reducer)
   * - ``@eager``
     - Force evaluation at scope creation rather than on first access
   * - ``@extend(*refs)``
     - Inherit from other scopes explicitly (for package-level union mounts)
   * - ``evaluate(*scopes)``
     - Resolve and union-mount one or more scopes into a single dependency graph


Python modules as scopes
-------------------------

The ``@scope`` classes above are a teaching convenience — the real-world style is
plain Python modules, just like pytest fixtures don't require a class. Every
``@scope`` class maps directly to a module file; pass it to ``evaluate()`` the same
way:

.. code-block:: python

   import sqlite_database   # sqlite_database.py with @extern / @resource / @public
   import user_repository   # user_repository/ package

The same decorators work on module-level functions exactly as on class methods. A
subpackage becomes a nested scope — ``user_repository/request_scope/`` is the
module equivalent of a nested ``@scope class RequestScope``.

Use ``@extend`` in a package's ``__init__.py`` to declare the composition, then
``evaluate()`` receives the single package:

.. literalinclude:: ../../tests/fixtures/app_di/__init__.py
   :language: python
   :start-after: # [docs:module-extend]
   :end-before: # [/docs:module-extend]

.. code-block:: python

   import myapp

   root = evaluate(myapp, modules_public=True).app(database_path=":memory:")

Runnable module-based equivalents of all tutorial examples are in
:github:`tests/test_readme_package_examples.py`,
using the fixture package at
:github:`tests/fixtures/app_di/`.

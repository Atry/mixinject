Getting Started with Overlay Language
=====================================

The Step 4 Python code works, but it has a structural problem: **business logic
and I/O are tangled together**. Consider ``user_id`` in ``HttpHandlers``:

.. code-block:: python

   def user_id(request: BaseHTTPRequestHandler) -> int:
       return int(request.path.split("/")[-1])

This one function mixes three concerns: reading ``request.path`` (I/O), splitting
on ``"/"`` (a business decision about URL format), and parsing the last segment as
an integer (another business decision). The path separator, SQL queries, and
format templates are all hardcoded in Python — changing any of them means
changing Python code.

The Overlay language solves this by separating the application into three layers:

- **Python FFI** wraps individual stdlib calls in ``@scope`` adapters — one class
  per operation (``sqlite3.connect``, ``str.split``, ``wfile.write``). Each adapter
  declares its inputs as ``@extern`` and exposes a single ``@public @resource``
  output. The adapter contains **zero business logic**.
- **``.oyaml`` files** contain all application logic, written in the Overlay
  language. The Overlay language is not just a configuration format — it is a
  complete language with lexical scoping, nested scopes, deep-merge composition,
  and lazy evaluation. These features make it more natural than Python for
  expressing business logic, which is inherently declarative ("the user ID is
  the last URL segment", "the response format is
  ``total={total} current={current}``").
- **Configuration values** (SQL queries, format strings, host/port) are pure
  YAML scalars, gathered in one place.

Business logic written in ``.oyaml`` is **portable**: it is decoupled from the
Python FFI layer. Swap the FFI adapters and the same ``.oyaml`` logic runs against
a different runtime — mock adapters for unit testing, a different language's
stdlib for cross-platform deployment, or instrumented adapters for profiling.
With Python ``@scope`` decorators, business logic is locked to the Python runtime
and cannot be extracted or retargeted.

Below is the same Step 4 web application rewritten in this style.


Python FFI adapters
-------------------

Each ``@scope`` class wraps exactly one stdlib operation. Below are three
representative adapters; the full module
(:github:`tests/fixtures/app_oyaml/stdlib_ffi/FFI.py`)
contains 10 more following the same pattern.

``SqliteConnectAndExecuteScript`` — multiple inputs, single output:

.. literalinclude:: ../../tests/fixtures/app_oyaml/stdlib_ffi/FFI/SqliteConnectAndExecuteScript.py
   :language: python

``GetItem`` — generic ``sequence[index]`` operation:

.. literalinclude:: ../../tests/fixtures/app_oyaml/stdlib_ffi/FFI/GetItem.py
   :language: python

``HttpSendResponse`` — chained I/O, send status + headers + body:

.. literalinclude:: ../../tests/fixtures/app_oyaml/stdlib_ffi/FFI/HttpSendResponse.py
   :language: python

Notice what is *not* here: no SQL queries, no ``"/"`` separator, no format string,
no ``:memory:`` path, no port number. Those are all business decisions that live
in the ``.oyaml``.


``.oyaml`` composition
----------------------

An ``.oyaml`` file describes a **dependency graph**, not an execution sequence.
There is no top-to-bottom control flow — the runtime evaluates resources lazily,
on demand. Think spreadsheet cells, not shell scripts.

The business logic lives in ``Library.oyaml``, which references FFI adapters
through abstract declarations (``FFI:`` scope with ``[]`` slots). A concrete FFI
module (``stdlib_ffi/FFI.py``) overrides these slots at composition time. This
separation means the business logic is portable — swap ``stdlib_ffi`` for a
different FFI implementation and the ``.oyaml`` files need no changes.

The following sections walk through ``Library.oyaml`` one scope at a time,
introducing new language concepts as they appear.


``SQLiteDatabase`` — extern, inheritance, wiring, projection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. literalinclude:: ../../tests/fixtures/app_oyaml/Library.oyaml
   :language: yaml
   :start-after: # [docs:sqlite-database]
   :end-before: # [/docs:sqlite-database]

Four new concepts:

- **``field: []``** — an **extern declaration**, the ``.oyaml`` equivalent of
  ``@extern``. The value must come from a parent scope or the caller.
- **``- [FFI, SqliteConnectAndExecuteScript]``** — **inheritance**. ``_db`` inherits
  the FFI adapter, gaining all of its resources (``connection``).
- **``database_path: [database_path]``** — **wiring**. The reference ``[database_path]``
  is a lexical lookup: search outward through enclosing scopes until a field
  named ``database_path`` is found.
- **``connection: [_db, connection]``** — **path navigation**. Access the
  ``connection`` resource on the child scope ``_db``. The leading underscore on
  ``_db`` makes it private; ``connection`` is the public-facing projection.


``UserRepository`` (app-scoped part) — nested scope, scope-as-dataclass
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. literalinclude:: ../../tests/fixtures/app_oyaml/Library.oyaml
   :language: yaml
   :start-after: # [docs:user-repository-app]
   :end-before: # [/docs:user-repository-app]

- **``User:``** is a **nested scope** with two extern fields — the ``.oyaml``
  equivalent of ``@scope class User`` with ``@public @extern`` fields. It acts as a
  dataclass constructor: ``current_user`` (below) will supply values for
  ``user_id`` and ``name``.
- **``connection: []``** declares that ``UserRepository`` expects a ``connection``
  from outside. When composed with ``SQLiteDatabase`` inside ``app``, this extern
  is satisfied by ``SQLiteDatabase.connection`` — resolved by name through
  lexical scoping.


``UserRepository.RequestScope`` — ANF style, cross-scope references
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. literalinclude:: ../../tests/fixtures/app_oyaml/Library.oyaml
   :language: yaml
   :start-after: # [docs:user-repository-request-scope]
   :end-before: # [/docs:user-repository-request-scope]

This section demonstrates **A-Normal Form (ANF)**: every intermediate result
must be bound to a named field. You cannot write
``GetItem(sequence=SqliteRowQuery(...).row, index=0)`` — instead, ``_row`` holds
the query result, and ``_identifier`` extracts column 0 from ``_row.row``. The
cost is verbosity; the benefit is that every intermediate value is inspectable
and independently composable.

**Cross-scope lexical reference:** ``connection: [connection]`` inside
``RequestScope`` finds ``UserRepository.connection`` — the lexical scope chain
searches outward through parent, grandparent, etc. No import statement is
needed; the scope hierarchy *is* the namespace.

**Constructing ``current_user``:** Instead of calling ``User(user_id=..., name=...)``,
the ``.oyaml`` directly defines ``current_user`` as a scope with two fields. The
``User`` scope-as-dataclass above establishes the field names; here those same
names are filled with concrete values.


``HttpHandlers`` — flat inheritance, qualified this
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. literalinclude:: ../../tests/fixtures/app_oyaml/Library.oyaml
   :language: yaml
   :start-after: # [docs:http-handlers]
   :end-before: # [/docs:http-handlers]

**Flat inheritance:** ``RequestScope`` inherits *two* FFI adapters in its
inheritance list (``- [FFI, ExtractUserId]``, ``- [FFI, HttpSendResponse]``). Their
``@extern`` and ``@resource`` fields all merge into ``RequestScope``'s own field
namespace. The last list item (the mapping starting with ``request: []``) defines
``RequestScope``'s own fields.

**Lexical scoping across scope boundaries:** ``[user_count]`` inside
``RequestScope`` searches outward and finds ``HttpHandlers.user_count``. At this
point ``user_count`` is just an extern ``[]`` — its actual value comes from
``UserRepository`` after deep merge (explained below).

**Qualified this: ``[RequestScope, ~, written]``** — instead of declaring
``written: []`` and writing ``response: [written]``, this navigates the runtime
composition graph to access the ``written`` property inherited from
``HttpSendResponse``. The advantage: if ``HttpSendResponse`` is accidentally not
composed, this fails with an error instead of silently creating an empty scope.


``NetworkServer`` — deep merge, config scoping
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. literalinclude:: ../../tests/fixtures/app_oyaml/Library.oyaml
   :language: yaml
   :start-after: # [docs:network-server]
   :end-before: # [/docs:network-server]

All the scopes above live in ``Library.oyaml``. They reference ``[FFI, Xxx]`` which
resolves to abstract declarations at the top of the file — no concrete Python
code is involved yet.


``Apps.oyaml`` — integration entry point
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Apps.oyaml`` is a separate file that inherits the real FFI implementation and
the Library, then defines concrete application entries:

.. literalinclude:: ../../tests/fixtures/app_oyaml/Apps.oyaml
   :language: yaml
   :start-after: # [docs:apps-oyaml]
   :end-before: # [/docs:apps-oyaml]

**Library/FFI separation:** ``- [stdlib_ffi]`` makes the real ``FFI`` module
(Python ``@scope`` classes) visible. ``- [Library]`` makes the business logic
visible. When composed, ``stdlib_ffi.FFI`` (real implementations) deep-merges
with ``Library.FFI`` (abstract declarations), and the real ``@resource`` methods
override the ``[]`` slots. The business logic never imports Python directly.

**Portability:** To run the same business logic on a different runtime, replace
``- [stdlib_ffi]`` with a different FFI package — the ``Library.oyaml`` file needs
no changes. To test with mocks, provide a mock FFI module instead of
``stdlib_ffi``.

**"What Color Is Your Function?"** (`blog post <https://journal.stuffwithstuff.com/2015/02/01/what-color-is-your-function/>`_):
The same ``Library.oyaml`` runs unchanged on both synchronous and asynchronous
runtimes. Replacing ``- [stdlib_ffi]`` with ``- [async_ffi]`` swaps the FFI layer
to one built on ``aiosqlite`` + ``starlette``
(:github:`implementation <tests/fixtures/app_oyaml/async_ffi/FFI/>`) — the business
logic never knows whether it is sync or async. Function color is confined
entirely to the FFI boundary; ``Library.oyaml`` itself is *colorless*.

**Composition via inheritance:** ``memory_app`` inherits four scopes via
qualified this (``[Apps, ~, SQLiteDatabase]`` etc.) because these scopes are
inherited properties, not own properties of ``Apps.oyaml``. This is not four
separate instances — it is a single scope with all four merged together. The
last list item supplies concrete values for every ``[]`` extern.

**Deep merge:** Both ``UserRepository`` and ``HttpHandlers`` define a
``RequestScope``. When composed inside ``memory_app``, these merge by name into a
single ``RequestScope``. After merging:

- ``user_id`` (from ``HttpHandlers.RequestScope`` via ``ExtractUserId``) becomes
  visible to ``UserRepository.RequestScope``, which uses it to look up
  ``current_user``
- ``current_user_name`` (from ``UserRepository.RequestScope``) becomes visible to
  ``HttpHandlers.RequestScope``, which uses it in ``_format``

Neither scope imports or references the other — deep merge makes their fields
mutual siblings automatically. This is the most powerful feature of the Overlay
language: cross-cutting concerns compose without glue code.

**Config value scoping:** App-lifetime values (``database_path``, ``host``, ``port``)
live directly in ``memory_app``. Request-lifetime values (``user_query_sql``,
``path_separator``, ``response_template``) live in ``memory_app.RequestScope`` — they
are only needed during request handling.


Syntax quick reference
----------------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Syntax
     - Meaning
   * - ``field: []``
     - **Extern** — value must be provided by a parent scope or caller
   * - ``field: [other]``
     - **Lexical reference** — look up ``other`` in the lexical scope chain
   * - ``field: [child, property]``
     - **Path navigation** — access ``property`` on ``child``
   * - ``field: [Scope, ~, symbol]``
     - **Qualified this** — access inherited ``symbol`` through the runtime graph
   * - ``field: "literal"``
     - **Scalar value** — string, number, etc.
   * - ``_field: ...``
     - **Private** — not visible to external callers (leading underscore)
   * - ``Scope:`` with a mapping
     - **Nested scope** — a child scope with its own fields
   * - ``Scope:`` with a list
     - **Inheritance** — ``- [Parent]`` items are inherited scopes; the last item (a mapping) defines own fields


Python vs Overlay language
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - Aspect
     - Python ``@scope``
     - Overlay language (``.oyaml``)
   * - Composition
     - Manual ``@extend`` + ``RelativeReference``
     - Inheritance list: ``- [Parent]``
   * - Dependency injection
     - ``@extern`` parameter names
     - ``field: []`` + lexical scope chain
   * - Expression style
     - Nested function calls
     - ANF: every intermediate has a name
   * - Cross-cutting concerns
     - Explicit adapter / glue code
     - Deep merge: same-named scopes auto-merge
   * - Accessing inherited members
     - ``self.xxx`` / parameter injection
     - Qualified this: ``[Scope, ~, symbol]``
   * - Business logic location
     - Mixed with I/O in Python
     - Separate ``.oyaml`` file, portable across FFI
   * - Configuration
     - Kwargs at call site
     - Scalar values in ``memory_app:`` scope


Evaluation
----------

.. code-block:: python

   import tests.fixtures.app_oyaml as app_oyaml
   from overlay.language import evaluate

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

Swapping configuration is just a different entry in ``Apps.oyaml`` — the Python
FFI adapters and ``Library.oyaml`` never change. Swapping the FFI layer is just a
different ``@scope`` module — the ``.oyaml`` business logic never changes.

Runnable tests for this example are in
:github:`tests/test_readme_package_examples.py`,
using the fixture package at
:github:`tests/fixtures/app_oyaml/`.

The full language specification is in :doc:`specification`.

The semantics of the Overlay language are grounded in the
`Overlay-Calculus <https://arxiv.org/abs/2602.16291>`_, a formal calculus of
overlays.

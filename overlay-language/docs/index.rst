Overlay Language
================

``overlay.language`` is a dependency injection framework with pytest-fixture
syntax, plus a configuration language for declarative programming. The package
has two parts:

The **Python decorator API** (``@scope``, ``@extern``, ``@resource``) gives you
dependency injection with pytest-fixture syntax — declare what a function needs
and the framework wires it up. Each module owns only its own concern; cross-
cutting behaviour layers on via ``@patch`` without touching the original code.
App-scoped singletons and per-request resources coexist naturally.
See :doc:`tutorial`.

The **Overlay language** is a configuration language written in ``.oyaml`` /
``.ojson`` / ``.otoml`` files. SQL queries, format strings, URL patterns — all
the business decisions that clutter Python code — live in the Overlay language
instead, where independent modules deep-merge by name without glue code —
dissolving the
`Expression Problem <https://en.wikipedia.org/wiki/Expression_problem>`_.

If you have ever struggled to mock a service that tangles I/O with business
logic, or dreaded porting an application from sync to async, or needed to swap
between providers without rewriting half your Python — the Overlay language can
help. Despite looking like a configuration format, it is also a statically typed
modern programming language based on
`Overlay-Calculus <https://arxiv.org/abs/2602.16291>`_, which is provably more
expressive than λ-calculus, so it can express your entire business logic — not
just configuration. Move that logic into the Overlay language and Python reduces
to thin I/O adapters that are trivial to mock or replace. The same Overlay code runs against any set of adapters and the business logic
never changes, even when you
port your synchronous program to async — the problem known as
`function colour <https://journal.stuffwithstuff.com/2015/02/01/what-color-is-your-function/>`_.
See :doc:`overlay-language-tutorial`.

:doc:`installation`
   Install the package from PyPI.

:doc:`tutorial`
   Getting started with the Python decorator API — build a web application
   step by step using ``@scope``, ``@extern``, and ``@resource``.

:doc:`overlay-language-tutorial`
   Getting started with the Overlay language — rewrite the same application
   in ``.oyaml``, separating business logic from I/O, then switch the
   underlying framework to asyncio without changing your code.

:doc:`specification`
   Full language specification for the Overlay language.

`API Reference <api/overlay.language.html>`__
   Python API reference (auto-generated).

.. toctree::
   :hidden:

   installation
   tutorial
   overlay-language-tutorial
   specification
   API Reference <api/overlay.language>

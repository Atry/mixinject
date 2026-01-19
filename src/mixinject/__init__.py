"""
mixinject: A dependency injection framework with pytest-fixture-like semantics.

Design Philosophy
=================

mixinject implements a dependency injection framework that combines pytest fixture-like semantics
with hierarchical resource structures and mixin composition patterns, inspired by
https://github.com/atry/mixin and https://github.com/mxmlnkn/ratarmount/pull/163.

Key Terminology
---------------

**Resource**
    A named injectable value defined via decorators like :func:`resource`, :func:`patch`,
    :func:`patch_many`, or :func:`merge`.

**Scope**
    An object that contains resources, accessed via attribute access (``.`` operator).
    Scopes can be nested to form hierarchical structures, analogous to a filesystem directory
    hierarchy. See :class:`Scope`.

**Lexical Scope**
    The lookup chain for resolving resources, scanning from inner to outer layers.
    See :data:`CapturedScopes`.

**Mixin**
    A value producer that participates in resource evaluation. There are three types:
    :class:`Merger` (creates values from patches), :class:`Patcher` (provides patches),
    and Semigroup (both Merger and Patcher). See :data:`Mixin`.

**Merger**
    A type of Mixin that creates a resource value by aggregating patches.
    See :class:`Merger`.

**Patcher**
    A type of Mixin that provides patches to be applied to a Merger's result.
    See :class:`Patcher`.

**Semigroup**
    A type of Mixin that is BOTH Merger AND Patcher simultaneously. This enables
    commutative composition where any item can serve as the merger while others
    contribute patches. Example: :func:`scope` creates a semigroup for nested
    Scope composition.

**Endofunction**
    A function of type ``Callable[[T], T]`` that transforms a value of type ``T`` into another
    value of the same type. This is a common patch type used with :func:`resource`. See :data:`Endofunction`.

Core Design Principle: Explicit Decorator Marking
==================================================

All injectable definitions **MUST** be explicitly marked with one of these decorators:

- :func:`resource`: Creates a merger that applies endo patches (``Callable[[T], T]``)
- :func:`patch`: Provides a single patch to an existing resource
- :func:`patch_many`: Provides multiple patches to an existing resource
- :func:`merge`: Creates a merger with custom aggregation strategy
- :func:`extern`: Declares a parameter placeholder (syntactic sugar for empty :func:`patch_many`)

Bare callables (functions without decorators) are **NOT** automatically injected.
This explicit-only design makes dependency injection predictable and self-documenting.

Example::

    from mixinject import resource, patch, mount

    # ✓ CORRECT: Explicitly decorated
    @resource
    def greeting() -> str:
        return "Hello"

    @patch
    def greeting() -> Callable[[str], str]:
        return lambda s: s + "!"

    # ✗ INCORRECT: Bare callable (will be ignored)
    def ignored_function() -> str:
        return "This won't be injected"

    root = mount(...)
    root.greeting  # "Hello!"
    root.ignored_function  # AttributeError: 'CachedScope' object has no attribute 'ignored_function'

Union Filesystem Analogy
========================

If we make an analogy to union filesystems:

- :class:`Scope` objects are like directory objects
- Resources are like files
- Modules, packages, callables, and :class:`ScopeDefinition` are filesystem definitions before mounting
- The compiled result (from :func:`mount`) is a concrete :class:`Scope` that implements resource access

Merger/Patcher Architecture
=============================

Resource Evaluation Algorithm
-----------------------------

When evaluating a resource, the system collects all Merger/Patcher items and applies
the following algorithm:

1. **Pure Merger** (Merger but NOT Patcher): If exactly one exists, it becomes the
   selected merger. All other items are treated as patches.

2. **Multiple Pure Mergers**: Raises ``ValueError`` (ambiguous which should be the base).

3. **No Pure Mergers, but Semigroups exist**: One semigroup is arbitrarily selected as
   the merger (assumes commutativity), and the rest are treated as patches.

4. **No Mergers at all**: Raises ``NotImplementedError`` (no way to create the resource).

Definition Types and Their Roles
---------------------------------

+-------------------+----------+---------+------------------------------------------+
| Decorator         | Merger? | Patcher?| Description                              |
+===================+==========+=========+==========================================+
| @resource         | Yes      | No      | Pure merger expecting endo patches      |
+-------------------+----------+---------+------------------------------------------+
| @merge       | Yes      | No      | Pure merger with custom aggregation     |
+-------------------+----------+---------+------------------------------------------+
| @patch            | No       | Yes     | Pure patcher providing a single patch    |
+-------------------+----------+---------+------------------------------------------+
| @patch_many          | No       | Yes     | Pure patcher providing multiple patches  |
+-------------------+----------+---------+------------------------------------------+
| @extern        | No       | Yes     | Pure patcher providing no patches        |
+-------------------+----------+---------+------------------------------------------+
| @scope            | Yes      | Yes     | Semigroup for nested Scope creation      |
+-------------------+----------+---------+------------------------------------------+

.. todo::
    Support phony targets for marking Semigroups that return ``None``.

    Similar to ``.PHONY`` targets in Makefiles, phony resources are primarily used
    to trigger side effects rather than produce values. This is useful for scenarios like:

    - Initialization operations (e.g., warming up database connection pools)
    - Resource cleanup (e.g., closing file handles)
    - Aggregation operations that trigger multiple dependencies

    Design considerations:

    1. **Declaration method**: Add ``@phony`` decorator to mark resource definitions returning ``None``::

           @phony
           def initialize_logging(config: Config) -> None:
               logging.basicConfig(level=config.log_level)

    2. **Type safety**: Phony resources should have type ``None`` and return ``None`` when accessed::

           root.initialize_logging  # Trigger side effect, returns None

    3. **Semigroup semantics**: When merging multiple phony definitions, all side effects are executed.
       **Important**: Users must ensure multiple phony definitions are commutative and do not depend on execution order::

           @phony
           def setup():
               register_handler_a()  # Must be independent from other setup side effects

           @phony
           def setup():
               register_handler_b()  # Must be independent from other setup side effects

    4. **Dependency tracking**: Phony resources can depend on other resources, ensuring dependencies are ready before side effects execute::

           @phony
           def warmup_cache(database: Database, cache: Cache) -> None:
               cache.populate_from(database)

    5. **Difference from ``@resource``**:

       - ``@resource`` return values are cached and can be depended on by other resources
       - ``@phony`` returns ``None``, primarily for triggering side effects, with multiple definitions merged as Semigroup

    6. **Decorator table update**:

       +-------------------+----------+---------+------------------------------------------+
       | @phony            | Yes      | Yes     | Semigroup for side-effect-only resources |
       +-------------------+----------+---------+------------------------------------------+

.. todo::
    Support specifying ``PurePath`` via type annotation to locate dependencies.

    Current dependency resolution is based on looking up parameter names in the symbol table,
    requiring traversal of closure levels. Using ``Annotated`` and ``PurePath`` allows explicit
    specification of relative paths for dependencies, avoiding symbol table lookups::

        # Desired syntax
        @resource
        def connection_pool(
            database_url: Annotated[URL, ResourceReference.from_pure_path(PurePath("../../config/database_url"))]
        ):
            return create_connection_pool(database_url)

        # Roughly equivalent to current syntax
        @resource
        def connection_pool(config: Scope):
            return create_connection_pool(config.database_url)

    The former explicitly specifies the location of ``database_url``, while the latter requires
    looking up the closure level where ``config`` is located in the symbol table.

    The advantage of ``ResourceReference`` is that it can access resources not in the lexical scope.
    Even if ``config`` is not in the current lexical scope's symbol table, ``../../config`` can still
    directly locate it through the path.

Combining Definitions
---------------------

Multiple definitions for the same resource name are combined using the algorithm above.
Common patterns:

**Resource + Patches** (most common)::

    @resource
    def value() -> int:
        return 10

    @patch
    def value() -> Callable[[int], int]:
        return lambda x: x * 2

    # Result: 20 (base value 10 transformed by patch)

**Merger + Patches** (custom aggregation)::

    @merge
    def tags() -> type[frozenset]:
        return frozenset

    @patch
    def tags() -> str:
        return "tag1"

    @patch
    def tags() -> str:
        return "tag2"

    # Result: frozenset({"tag1", "tag2"})

**Multiple Scopes** (semigroup composition)::

    @scope()
    class Base:
        @resource
        def foo() -> str:
            return "base_foo"

    @scope()
    class Extension:
        @resource
        def bar() -> str:
            return "ext_bar"

    # Result: Scope with both foo and bar resources (merged)

Dependency Resolution
=====================

Name-Based Resolution
---------------------

Dependency injection is **always based on parameter names**, not types. The parameter resolution
algorithm (similar to https://github.com/atry/mixin) automatically searches for dependencies
in the lexical scope chain (from inner to outer).

Simple Dependency Example::

    @resource
    def my_resource(some_dependency: str) -> float:
        return float(some_dependency)

The parameter ``some_dependency`` is resolved by searching the lexical scope chain for a resource
named ``some_dependency``.

Complex Path Access via Scope
------------------------------

To access resources via complex paths, you must use an explicit :class:`Scope` parameter::

    @resource
    def my_callable(uncle: Scope) -> float:
        return uncle.path.to.resource

This searches the lexical scope chain for the first :class:`Scope` that defines a resource
named ``uncle``, then accesses ``path.to.resource`` under that :class:`Scope`.

Scope-Returning Resources as Symbolic Links
--------------------------------------------

If a callable returns a :class:`Scope`, that resource acts like a symbolic link
(similar to https://github.com/mxmlnkn/ratarmount/pull/163)::

    @resource
    def my_scope(uncle: Scope) -> Scope:
        return uncle.path.to.another_scope

This finds the first :class:`Scope` in the lexical scope that defines ``uncle``, then accesses
nested resources through that :class:`Scope`.

Same-Name Dependency (Extending Outer Definitions)
---------------------------------------------------

When a parameter name matches the resource name, it skips the current :class:`Scope` and
looks for the same-named resource in outer scopes. This pattern allows extending or
transforming an outer scope's definition::

    class Outer:
        @resource
        def counter() -> int:
            return 0

        @scope()
        class Inner:
            @resource
            def counter(counter: int) -> int:  # same-name parameter
                return counter + 1  # extends outer's counter

    root = mount(Outer)
    root.counter  # 0
    root.Inner.counter  # 1 (outer's 0 + 1)

**Comparison with @patch endo:**

Two patterns look similar but work differently:

1. **@resource with same-name parameter** (Merger, looks up from PARENT scope)::

       @resource
       def counter(counter: int) -> int:  # parameter resolved from outer
           return counter + 1

2. **@patch returning endo** (Patcher, endo receives base value from Merger)::

       @patch
       def counter() -> Callable[[int], int]:
           return lambda counter: counter + 1  # endo argument is base value

The key difference:

- ``@resource`` with same-name parameter creates a **new Merger** that shadows the
  outer definition. The parameter is resolved at compile-time from the outer scope's
  symbol table.
- ``@patch`` returning an endo creates a **Patcher** that transforms an existing
  Merger's result. The endo function's argument receives the base value at runtime.

Merging and Composition
========================

Module and Package Merging
---------------------------

When merging modules and packages, mixinject uses an algorithm similar to
https://github.com/atry/mixin and https://github.com/mxmlnkn/ratarmount/pull/163.

Same-Named Callable Merging Rules
----------------------------------

When merging N same-named definitions, the Merger/Patcher evaluation algorithm applies:

- At most **1** pure merger (:func:`resource` or :func:`merge`) is allowed
- Any number of pure patchers (:func:`patch`, :func:`patch_many`, :func:`extern`) are allowed
- Semigroups (:func:`scope`) can serve as either merger or patcher

Union Mounting at Entry Point
------------------------------

At the framework entry point (:func:`mount`), users can pass multiple packages, modules,
or objects, which are union-mounted into a unified root :class:`Scope`, similar to
https://github.com/mxmlnkn/ratarmount/pull/163.

Parameter Injection Pattern
============================

Concept
-------

A resource can be defined **solely** by :func:`patch`, :func:`patch_many`, or :func:`extern`
decorators, without a base definition from :func:`resource` or :func:`merge`. This is
the **parameter injection pattern** - a way to declare that a value should be provided from
an outer scope via :class:`InstanceScope` or :meth:`StaticScope.__call__`.

Two Equivalent Approaches
--------------------------

**Recommended: @extern decorator**::

    @extern
    def settings(): ...

**Alternative: @patch with identity endo**::

    @patch
    def settings() -> Callable[[dict], dict]:
        return lambda x: x  # identity function

Both approaches register the resource name in the symbol table and expect the base value
to be provided via :meth:`StaticScope.__call__`. The ``@extern`` decorator is syntactic sugar
that makes the intent clearer.

How It Works
------------

When a parameter-only resource is accessed:

1. The resource name is found in the symbol table (registered by ``@extern`` or ``@patch``)
2. The base value is looked up from :class:`InstanceScope` (created via ``StaticScope.__call__``)
3. All patches are applied (identity patches pass through unchanged)
4. The final value is returned

If no base value is provided, ``NotImplementedError`` is raised.

Example
-------

::

    # config.py
    from mixinject import parameter, resource

    @extern
    def settings(): ...

    @resource
    def connection_string(settings: dict) -> str:
        return f"{settings['host']}:{settings['port']}"

    # main.py
    from mixinject import mount

    root = mount(config)(settings={"host": "db.example.com", "port": "3306"})
    assert root.connection_string == "db.example.com:3306"

Use Cases
---------

This pattern is useful for:

- **Configuration parameters**: Modules declare they need configuration without defining values
- **Dependency injection**: Inject external dependencies without hardcoding
- **Multi-version support**: Combine the same module with different injected values

Scope as Callable
=================

Every :class:`Scope` object is also callable, supporting direct parameter injection.

Implementation
--------------

:class:`Scope` implements ``__call__(**kwargs)``, returning a new :class:`Scope` of the same type
creating an :class:`InstanceScope` that stores kwargs directly for lookup.

Example::

    # Create a Scope and inject values using mount
    @scope()
    class Config:
        @extern
        def setting(): ...
        @extern
        def count(): ...

    scope = mount(Config)
    new_scope = scope(setting="value", count=42)

    # Access injected values
    assert new_scope.setting == "value"
    assert new_scope.count == 42

Primary Use Case
----------------

The primary use of Scope as Callable is to provide base values for parameter injection.
By using :meth:`Scope.__call__` in an outer scope to inject parameter values, resources in
modules can access these values via symbol table lookup::

    # Provide base value in outer scope via mount
    @scope()
    class Config:
        @extern
        def db_config(): ...

    outer_scope = mount(Config)(db_config={"host": "localhost", "port": "5432"})

    outer_scope: CapturedScopes = (outer_scope,)

    # Resources in modules can obtain this value via same-named parameter
    @scope()
    class Database:
        @extern
        def db_config(): ...

        @resource
        def connection(db_config: dict) -> str:
            return f"{db_config['host']}:{db_config['port']}"

Callables can be used not only to define resources but also to define and transform Scope objects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import ast
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import cached_property, reduce
import importlib
import importlib.util
from inspect import signature
import logging
import os
from pathlib import PurePath
import pkgutil
from types import ModuleType
from typing import (
    Any,
    AsyncContextManager,
    Awaitable,
    Callable,
    ChainMap,
    ContextManager,
    Final,
    Generic,
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    Never,
    NewType,
    ParamSpec,
    Sequence,
    TypeAlias,
    TypeVar,
    assert_never,
    cast,
    final,
    override,
)
from weakref import WeakValueDictionary


import weakref

_logger: Final[logging.Logger] = logging.getLogger(__name__)

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)
TPatch_co = TypeVar("TPatch_co", covariant=True)
TPatch_contra = TypeVar("TPatch_contra", contravariant=True)
TResult_co = TypeVar("TResult_co", covariant=True)

P = ParamSpec("P")


class HasDict:
    """
    Extendable helper class that adds ``__dict__`` slot for classes that need ``@cached_property``.

    When using ``@dataclass(slots=True)``, instances don't have ``__dict__``,
    which prevents ``@cached_property`` from working. Inheriting from this class
    adds a ``__dict__`` slot, allowing ``@cached_property`` to function properly.
    """

    __slots__ = ("__dict__",)


@dataclass(kw_only=True, frozen=True, eq=False)
class Symbol(ABC):
    """
    Base class for nodes in the dependency graph.

    Conceptual Layer Distinction
    ============================

    This system has two distinct layers that should not be conflated:

    **Symbol Layer (Dependency Graph Nodes)**

    - ``Symbol``: Base class
    - ``SymbolMapping``: Symbol containing nested resources
    - ``NestedSymbol``: Leaf Symbol (non-Mapping)
    - ``NestedSymbolMapping``: Nested Scope Symbol (IS-A Mapping)

    **Evaluator Layer (Resource Evaluators)**

    - ``Evaluator = Merger | Patcher``
    - ``Merger``: Merges patches to produce result
    - ``Patcher``: Provides patches
    - ``_ScopeSemigroup``: An Evaluator that implements both Merger and Patcher

    **Relationship**

    - ``NestedMergerSymbol.__call__`` returns ``Merger``
    - ``NestedPatcherSymbol.__call__`` returns ``Patcher``
    - ``NestedSymbolMapping.__call__`` returns ``_ScopeSemigroup`` (an Evaluator)

    ``_ScopeSemigroup`` is currently the only Semigroup Evaluator, but the system
    will support other Semigroups in the future. Semigroup is an Evaluator layer
    concept and should not be conflated with the Symbol layer.

    Refactoring Goals and Motivation
    ==================================

    Optimization Scenario
    ---------------------

    This refactoring aims to optimize **scenarios where massive Symbols are merged into a single Proxy after linearization**.

    **Definition of "massive"**: 100+ Symbols need to be merged.

    In complex dependency injection scenarios, a Scope may inherit from multiple base classes, each with its own
    inheritance chain. After linearization, looking up a single resource may require traversing 100+ Symbols. The
    current implementation traverses all Symbols at runtime and performs ``isinstance`` checks, which becomes a
    performance bottleneck in massive Symbol scenarios.

    Optimization Strategy
    ---------------------

    1. **Compile-time type classification**: When creating Symbol in ``SymbolMapping.__getitem__``,
       determine whether it's Merger/Patcher/Mapping based on Symbol type
    2. **Precompute indices**: Store type classification results in ``merger_base_indices``,
       ``patcher_base_indices``, ``mapping_base_indices``
    3. **Random access instead of traversal**: Proxy/JIT uses precomputed indices to directly access
       needed Symbols, eliminating runtime traversal and ``isinstance`` checks

    Typed Symbol Hierarchy
    ======================

    ::

        Symbol (ABC)
        │   @abstractmethod __call__(CapturedScopes) → Evaluator
        │
        ├── SymbolMapping (ABC, Mapping[Hashable, Symbol])
        │   │   __getitem__(key) → NestedMergerSymbol | NestedPatcherSymbol | NestedSymbolMapping
        │   │
        │   ├── StaticSymbolMapping (ABC)
        │   │   ├── RootSymbolMapping
        │   │   └── NestedSymbolMapping (IS-A Mapping, contains nested resources)
        │   │           __call__() → _ScopeSemigroup (an Evaluator: Merger ∩ Patcher)
        │   │           merger_base_indices: Mapping[NestedMergerSymbol, NestedSymbolIndex]
        │   │           patcher_base_indices: Mapping[NestedPatcherSymbol, NestedSymbolIndex]
        │   │           mapping_base_indices: Mapping[NestedSymbolMapping, NestedSymbolIndex]
        │   │
        │   └── InstanceSymbolMapping
        │
        ├── NestedMergerSymbol (subtype of former NestedSymbol)
        │       __call__() → Merger (not Patcher)
        │
        └── NestedPatcherSymbol (subtype of former NestedSymbol)
                __call__() → Patcher (not Merger)

    ``__call__`` Semantics
    ======================

    ``Symbol`` implements the ``EvaluatorGetter`` interface, i.e.::

        EvaluatorGetter: TypeAlias = Callable[[CapturedScopes], Evaluator]

    Calling ``symbol(captured_scopes)`` returns a ``Mixin`` (``Merger | Patcher``).
    Different subclasses have different return types:

    - ``NestedMergerSymbol.__call__`` → ``Merger`` (not Patcher)
    - ``NestedPatcherSymbol.__call__`` → ``Patcher`` (not Merger)
    - ``NestedSymbolMapping.__call__`` → ``_ScopeSemigroup`` (an Evaluator: Merger ∩ Patcher)

    Definition Type to Symbol Type Mapping
    =====================================

    ========================== ========================== ============================
    Definition Type            Generated Symbol            ``get_evaluator`` Return Type
    ========================== ========================== ============================
    ``_MergerDefinition``      ``_NestedMergerSymbol``     ``Merger`` (not Patcher)
    ``_ResourceDefinition``    ``_NestedResourceSymbol``   ``Merger`` (not Patcher)
    ``_SinglePatchDefinition`` ``_NestedSinglePatchSymbol`` ``Patcher`` (not Merger)
    ``_MultiplePatchDefinition`` ``_NestedMultiplePatchSymbol`` ``Patcher`` (not Merger)
    ``_DefinitionMapping``     ``DefinedSymbolMapping``    ``_ScopeSemigroup`` (Evaluator)
    ========================== ========================== ============================

    .. todo:: Inherit from ``EvaluatorGetter``. Add ``@abstractmethod __call__``.
    """

    @abstractmethod
    def generate_strict_super(self) -> Iterator[Symbol]:
        """
        Generate the strict super symbols (all direct and transitive bases, excluding self).

        "Strict super" follows the mathematical convention where a strict superset
        excludes the set itself. Similarly, this method yields all direct and transitive
        base symbols, but not the symbol itself.

        The result is linearized (stable, reproducible order) and deduplicated.
        No additional constraints (such as C3 linearization) are guaranteed.
        """


@dataclass(kw_only=True, frozen=True, eq=False)
class SymbolMapping(Symbol, Mapping[Hashable, "Symbol"]):
    """Base class for dependency graphs supporting O(1) equality comparison.

    Equal graphs are interned to the same object instance within the same root,
    making equality comparison a simple identity check (O(1) instead of O(n)).

    This class is immutable and hashable, suitable for use as dictionary keys.

    .. todo:: Inherit from ``Mapping[Hashable, EvaluatorGetter]``.
    """

    intern_pool: Final[
        weakref.WeakValueDictionary[Hashable, "NestedSymbolMapping | NestedSymbol"]
    ] = field(default_factory=weakref.WeakValueDictionary)

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other: object) -> bool:
        return self is other

    def __iter__(self) -> Iterator[Hashable]:
        seen: set[Hashable] = set()

        # Keys from self.definition (only if _DefinedSymbol)
        if isinstance(self, _DefinedSymbol):
            assert isinstance(self.definition, _DefinitionMapping)
            for key in self.definition:
                if key not in seen:
                    seen.add(key)
                    yield key

        # Keys from bases
        for base in cast(Iterator[SymbolMapping], self.generate_strict_super()):
            for key in base:
                if key not in seen:
                    seen.add(key)
                    yield key

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __getitem__(self, key: Hashable) -> "Symbol":
        """
        Get or create the child Symbol for the specified key.

        For defined symbols, delegates to ``Definition.compile()``.
        For synthetic symbols (inherited without local definition), creates
        a synthetic symbol via ``_compile_synthetic()``.
        """
        existing = self.intern_pool.get(key)
        if existing is not None:
            return existing

        # Compile based on whether this is a synthetic or defined symbol
        if isinstance(self, _SyntheticSymbol):
            compiled_symbol = _compile_synthetic(key, self)
        else:
            assert isinstance(self, _DefinedSymbol)
            assert isinstance(self.definition, _DefinitionMapping)
            nested_definition = self.definition.get(key)
            if nested_definition is not None:
                compiled_symbol = nested_definition.compile(self, cast(str, key))
            else:
                compiled_symbol = _compile_synthetic(key, self)

        self.intern_pool[key] = cast(
            "NestedSymbolMapping | NestedSymbol", compiled_symbol
        )
        return compiled_symbol


def _compile_synthetic(
    key: Hashable,
    outer_symbol: "SymbolMapping",
) -> "NestedSymbol | NestedSymbolMapping":
    """
    Create a NestedSymbol for inherited-only resources.

    For leaf resources (Merger, Resource, Patcher), creates a _SyntheticResourceSymbol
    that returns an empty Patcher (similar to @extern).

    For nested scopes (NestedSymbolMapping), creates a SyntheticSymbolMapping
    that properly merges base scopes.

    Validates that all base classes have consistent types using the
    generate_is_symbol_mapping + reduce(assert_equal, ...) pattern.
    """
    base_symbols = _collect_base_indices(outer_symbol, key)

    def generate_is_symbol_mapping() -> Iterator[bool]:
        """Generate bool indicating whether each base symbol is a SymbolMapping."""
        for base_symbol in base_symbols:
            yield isinstance(base_symbol, SymbolMapping)

    def assert_equal(a: T, b: T) -> T:
        if a != b:
            raise ValueError(
                "Inconsistent symbol types for same-named resource across bases"
            )
        return a

    try:
        is_symbol_mapping = reduce(assert_equal, generate_is_symbol_mapping())
    except TypeError as exception:
        # reduce raises TypeError when iterator is empty (no bases have this key)
        raise KeyError(key) from exception

    if is_symbol_mapping:
        return SyntheticSymbolMapping(
            key=key,
            outer=outer_symbol,
        )

    # For leaf resources, create _SyntheticResourceSymbol (empty Patcher)
    return _SyntheticResourceSymbol(
        key=key,
        outer=outer_symbol,
    )


class _SyntheticSymbol(ABC):
    """
    Marker base class for synthetic symbols (no local definition, only inherited).

    Synthetic symbols are created when a resource or nested scope is inherited from
    base classes but has no local definition in the current scope.

    Subclasses
    ==========

    - ``_SyntheticResourceSymbol``: For leaf resources (Merger, Resource, Patcher)
    - ``SyntheticSymbolMapping``: For nested scopes
    """


@dataclass(kw_only=True, frozen=True, eq=False)
class _DefinedSymbol(ABC):
    """
    Marker base class for defined symbols (has local definition in current scope).

    Defined symbols are created when a resource or nested scope has a local definition
    in the current scope. They have access to the full definition information.

    Subclasses
    ==========

    - ``_NestedMergerSymbol``, ``_NestedResourceSymbol``, etc.: For leaf resources
    - ``DefinedSymbolMapping``: For nested scopes
    - ``RootSymbolMapping``: For root symbol

    All subclasses have ``definition: Definition`` (narrowed from the base class type).
    """

    definition: Final["Definition"]


@dataclass(kw_only=True, frozen=True, eq=False)
class StaticSymbolMapping(HasDict, SymbolMapping):
    """
    .. todo:: Implement ``__getitem__`` for lazy creation of child dependency graphs.
    .. todo:: Implement ``__call__(captured_scopes: CapturedScopes) -> _ScopeSemigroup``
              to make ``NestedSymbolMapping`` become ``Callable[[CapturedScopes], _ScopeSemigroup]``.
    """

    @cached_property
    def instance_symbol(self) -> "InstanceSymbolMapping":
        """Cache for the corresponding InstanceSymbolMapping."""
        return InstanceSymbolMapping(prototype=self)


Mixin: TypeAlias = "Merger | Patcher"
"""A Merger or Patcher that participates in resource evaluation."""

TMixin_co = TypeVar("TMixin_co", bound="Merger | Patcher", covariant=True)


class MixinGetter(Generic[TMixin_co], ABC):
    """
    ABC for retrieving a Mixin from a CapturedScopes context.

    .. todo::

        After refactoring, ``NestedSymbol`` will inherit from this ABC,
        and the four ``_XxxMixinGetter`` implementation classes will
        be replaced by ``NestedSymbol`` subclasses:

        - ``_NestedMergerSymbol`` replaces ``_MergerMixinGetter``
        - ``_NestedResourceSymbol`` replaces ``_ResourceMixinGetter``
        - ``_NestedSinglePatchSymbol`` replaces ``_SinglePatchMixinGetter``
        - ``_NestedMultiplePatchSymbol`` replaces ``_MultiplePatchMixinGetter``

        This unifies the Symbol and MixinGetter hierarchies.
    """

    @abstractmethod
    def bind(self, captured_scopes: "CapturedScopes", /) -> TMixin_co:
        """Retrieve the Mixin for the given captured scopes."""
        ...


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class RootSymbolMapping(_DefinedSymbol, StaticSymbolMapping):
    """
    Root of a dependency graph.

    Each RootSymbolMapping instance has its own intern pool for interning
    NestedSymbolMapping nodes within that dependency graph.
    """

    def generate_strict_super(self) -> Iterator[Symbol]:
        """
        Root symbol has no strict super symbols.

        Since root is the top of the hierarchy, there are no direct or transitive bases.
        """
        return iter(())


class SymbolIndexSentinel(Enum):
    """Sentinel value for symbol indices indicating the symbol itself (not a base)."""

    OWN = auto()


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class OuterBaseIndex:
    """
    Index into outer symbol's linearized bases.

    Used when the nested symbol is inherited from one of the outer symbol's base classes.
    """

    index: Final[int]


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class OwnBaseIndex:
    """
    Index into the extend reference list (own bases).

    Used when the nested symbol is explicitly extended via the ``extend`` parameter
    in the ``@scope`` decorator.
    """

    index: Final[int]


PrimarySymbolIndex: TypeAlias = OuterBaseIndex | OwnBaseIndex | SymbolIndexSentinel
"""
The primary index identifying the source of a nested symbol.

- ``OuterBaseIndex``: Inherited from outer symbol's linearized bases
- ``OwnBaseIndex``: Explicitly extended via the ``extend`` parameter
- ``SymbolIndexSentinel.OWN``: The nested symbol itself (used as secondary_index)
"""

SecondarySymbolIndex: TypeAlias = int | SymbolIndexSentinel
"""
The secondary index within a primary base's linearized chain.

- ``int``: Position in the primary base's ``generate_strict_super()``
- ``SymbolIndexSentinel.OWN``: The primary base itself (not one of its strict super symbols)
"""


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class NestedSymbolIndex:
    """
    Two-dimensional index of Symbol in outer SymbolMapping, supporting O(1) random access.

    Basic Concept
    =============

    ``NestedSymbolIndex`` uses a two-dimensional index ``(primary_index, secondary_index)`` to locate
    a Symbol's position in its outer SymbolMapping's linearized inheritance chain.

    - ``primary_index``: Identifies the source of the nested symbol

      - ``OuterBaseIndex``: Inherited from outer's linearized bases
      - ``OwnBaseIndex``: Explicitly extended via ``extend`` parameter

    - ``secondary_index``: Position within that source's linearized chain

      - ``int``: Position in the source's ``generate_strict_super()``
      - ``SymbolIndexSentinel.OWN``: The source itself (not one of its strict super symbols)

    Index Semantics
    ===============

    The integer indices in ``OuterBaseIndex`` and ``OwnBaseIndex`` are plain array subscripts
    with no special meaning. ``SymbolIndexSentinel.OWN`` is needed because a symbol does not
    appear in its own ``generate_strict_super()`` - only its strict super symbols do.

    Index Examples
    ==============

    Given ``nested_symbol: NestedSymbolMapping`` with ``key`` in ``outer: SymbolMapping``,
    and integer indices ``i``, ``j``:

    - ``NestedSymbolIndex(primary_index=OuterBaseIndex(index=i), secondary_index=SymbolIndexSentinel.OWN)``::

        # outer_bases[i][key] itself
        outer_bases = tuple(outer.generate_strict_super())
        target = outer_bases[i][key]

    - ``NestedSymbolIndex(primary_index=OuterBaseIndex(index=i), secondary_index=j)``::

        # The j-th strict super symbol of outer_bases[i][key]
        outer_bases = tuple(outer.generate_strict_super())
        outer_nested = outer_bases[i][key]
        target = tuple(outer_nested.generate_strict_super())[j]

    - ``NestedSymbolIndex(primary_index=OwnBaseIndex(index=i), secondary_index=SymbolIndexSentinel.OWN)``::

        # extend_refs[i] itself
        extend_refs = nested_symbol.definition.bases
        target = _resolve_symbol_reference(extend_refs[i], outer, NestedSymbolMapping)

    - ``NestedSymbolIndex(primary_index=OwnBaseIndex(index=i), secondary_index=j)``::

        # The j-th strict super symbol of extend_refs[i]
        extend_refs = nested_symbol.definition.bases
        own_base = _resolve_symbol_reference(extend_refs[i], outer, NestedSymbolMapping)
        target = tuple(own_base.generate_strict_super())[j]

    JIT Optimization Use Cases
    ===========================

    This data structure is designed for JIT and Proxy optimization:

    1. **Eliminate runtime traversal**: JIT can directly access specific Symbols using indices,
       without traversing ``generate_strict_super()``

    2. **O(1) random access**: Given ``NestedSymbolIndex``, the Symbol's position can be directly
       computed with O(1) time complexity

    3. **Typed indices**: Combined with ``merger_base_indices``, ``patcher_base_indices``,
       ``mapping_base_indices``, JIT can directly access specific types of Symbols

    Collaboration with Typed Symbols
    ================================

    After refactoring, this index will be used for the following typed index properties:

    ::

        merger_base_indices: Mapping[NestedMergerSymbol, NestedSymbolIndex]
        patcher_base_indices: Mapping[NestedPatcherSymbol, NestedSymbolIndex]
        mapping_base_indices: Mapping[NestedSymbolMapping, NestedSymbolIndex]

    JIT Usage Example::

        # Directly access all Mergers without traversal and isinstance checks
        for merger, index in scope.symbol.merger_base_indices.items():
            mixin_result = merger(captured_scopes)  # Return type guaranteed to be Merger
    """

    primary_index: Final[PrimarySymbolIndex]
    secondary_index: Final[SecondarySymbolIndex]


@dataclass(kw_only=True, frozen=True, eq=False)
class NestedSymbol(HasDict, Symbol, MixinGetter["Merger | Patcher"]):
    """
    Leaf Symbol corresponding to non-Mapping resource definitions.

    This is the base class for all leaf Symbols. Subclasses implement
    ``bind`` to return the appropriate Mixin type.

    Subclass Hierarchy
    ==================

    - ``MergerSymbol[TPatch_contra, TResult_co]``: Returns ``Merger[TPatch_contra, TResult_co]``
    - ``PatcherSymbol[TPatch_co]``: Returns ``Patcher[TPatch_co]``

    Use ``isinstance`` checks for runtime type discrimination::

        if isinstance(nested_symbol, MergerSymbol):
            mixin = nested_symbol.bind(captured_scopes)  # Merger
        elif isinstance(nested_symbol, PatcherSymbol):
            mixin = nested_symbol.bind(captured_scopes)  # Patcher
    """

    outer: Final[SymbolMapping]
    key: Final[Hashable]

    @cached_property
    def base_indices(self) -> Mapping["NestedSymbol", int]:
        """Collect base_indices from outer's strict super symbols."""
        return _collect_base_indices(self.outer, self.key)

    @cached_property
    def depth(self) -> int:
        """Compute depth in O(1) by leveraging outer's cached depth."""
        if isinstance(self.outer, NestedSymbolMapping):
            return self.outer.depth + 1
        return 1

    @cached_property
    def getter(self) -> Callable[[CapturedScopes], "Node"]:
        """Create getter function for accessing this resource."""
        index = self.depth - 1
        if isinstance(self.key, str):
            return _make_jit_getter(self.key, index)
        return lambda captured_scopes: captured_scopes[index][self.key]

    def generate_strict_super(self) -> Iterator[Symbol]:
        """Generate the strict super symbols (all direct and transitive bases, excluding self)."""
        return iter(self.base_indices.keys())

    @abstractmethod
    def bind(self, captured_scopes: CapturedScopes, /) -> "Merger | Patcher":
        """Retrieve the Mixin for the given captured scopes."""


@dataclass(kw_only=True, frozen=True, eq=False)
class MergerSymbol(NestedSymbol, Generic[TPatch_contra, TResult_co]):
    """
    Intermediate base class for NestedSymbol subclasses that return Merger.

    Use ``isinstance(mixin, MergerSymbol)`` to check if a mixin returns a Merger.

    Type Parameters
    ===============

    - ``TPatch_contra``: The type of patches this Merger accepts (contravariant)
    - ``TResult_co``: The type of result this Merger produces (covariant)
    """

    @abstractmethod
    @override
    def bind(
        self, captured_scopes: CapturedScopes, /
    ) -> "Merger[TPatch_contra, TResult_co]":
        """Retrieve the Merger for the given captured scopes."""


@dataclass(kw_only=True, frozen=True, eq=False)
class PatcherSymbol(NestedSymbol, Generic[TPatch_co]):
    """
    Intermediate base class for NestedSymbol subclasses that return Patcher.

    Use ``isinstance(mixin, PatcherSymbol)`` to check if a mixin returns a Patcher.

    Type Parameters
    ===============

    - ``TPatch_co``: The type of patches this Patcher produces (covariant)
    """

    @abstractmethod
    @override
    def bind(self, captured_scopes: CapturedScopes, /) -> "Patcher[TPatch_co]":
        """Retrieve the Patcher for the given captured scopes."""


TResult = TypeVar("TResult")


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class _NestedMergerSymbol(
    _DefinedSymbol,
    MergerSymbol[TPatch_contra, TResult_co],
    Generic[TPatch_contra, TResult_co],
):
    """NestedSymbol for _MergerDefinition."""

    @cached_property
    def jit_compiled_function(
        self,
    ) -> Callable[[CapturedScopes], Callable[[Iterator[TPatch_contra]], TResult_co]]:
        """JIT-compiled function using mixin-based dependency resolution."""
        definition = cast(
            "_MergerDefinition[TPatch_contra, TResult_co]", self.definition
        )
        assert isinstance(
            self.key, str
        ), f"Merger key must be a string, got {type(self.key)}"
        return _resolve_dependencies_jit_using_symbol(
            self.outer,
            definition.function,
            self.key,
        )

    @override
    def bind(
        self, captured_scopes: CapturedScopes, /
    ) -> "Merger[TPatch_contra, TResult_co]":
        aggregation_function = self.jit_compiled_function(captured_scopes)
        return FunctionMerger(aggregation_function=aggregation_function)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class _NestedResourceSymbol(
    _DefinedSymbol, MergerSymbol["Endofunction[TResult]", TResult], Generic[TResult]
):
    """NestedSymbol for _ResourceDefinition.

    Returns ``Merger[Endofunction[T], T]`` which accepts endofunction patches.
    """

    @cached_property
    def jit_compiled_function(self) -> Callable[[CapturedScopes], TResult]:
        """JIT-compiled function using mixin-based dependency resolution."""
        definition = cast("_ResourceDefinition[TResult]", self.definition)
        assert isinstance(
            self.key, str
        ), f"Resource key must be a string, got {type(self.key)}"
        return _resolve_dependencies_jit_using_symbol(
            self.outer,
            definition.function,
            self.key,
        )

    @override
    def bind(
        self, captured_scopes: CapturedScopes, /
    ) -> "Merger[Endofunction[TResult], TResult]":
        base_value = self.jit_compiled_function(captured_scopes)
        return _EndofunctionMerger(base_value=base_value)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class _NestedSinglePatchSymbol(
    _DefinedSymbol, PatcherSymbol[TPatch_co], Generic[TPatch_co]
):
    """NestedSymbol for _SinglePatchDefinition."""

    @cached_property
    def jit_compiled_function(self) -> Callable[[CapturedScopes], TPatch_co]:
        """JIT-compiled function using mixin-based dependency resolution."""
        definition = cast("_SinglePatchDefinition[TPatch_co]", self.definition)
        assert isinstance(
            self.key, str
        ), f"Patch key must be a string, got {type(self.key)}"
        return _resolve_dependencies_jit_using_symbol(
            self.outer,
            definition.function,
            self.key,
        )

    @override
    def bind(self, captured_scopes: CapturedScopes, /) -> "Patcher[TPatch_co]":
        jit_func = self.jit_compiled_function

        def patch_generator() -> Iterator[TPatch_co]:
            yield jit_func(captured_scopes)

        return FunctionPatcher(patch_generator=patch_generator)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class _NestedMultiplePatchSymbol(
    _DefinedSymbol, PatcherSymbol[TPatch_co], Generic[TPatch_co]
):
    """NestedSymbol for _MultiplePatchDefinition."""

    @cached_property
    def jit_compiled_function(self) -> Callable[[CapturedScopes], Iterable[TPatch_co]]:
        """JIT-compiled function using mixin-based dependency resolution."""
        definition = cast("_MultiplePatchDefinition[TPatch_co]", self.definition)
        assert isinstance(
            self.key, str
        ), f"Patch key must be a string, got {type(self.key)}"
        return _resolve_dependencies_jit_using_symbol(
            self.outer,
            definition.function,
            self.key,
        )

    @override
    def bind(self, captured_scopes: CapturedScopes, /) -> "Patcher[TPatch_co]":
        jit_func = self.jit_compiled_function

        def patch_generator() -> Iterator[TPatch_co]:
            return (yield from jit_func(captured_scopes))

        return FunctionPatcher(patch_generator=patch_generator)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class _SyntheticResourceSymbol(_SyntheticSymbol, PatcherSymbol[Never]):
    """NestedSymbol for inherited-only leaf resources (no local definition).

    Similar to @extern, this produces an empty Patcher that contributes
    no patches to the Merger election algorithm. The actual Evaluator
    comes from base classes.

    Type parameter is ``Never`` because this Patcher never yields any patches.
    """

    @override
    def bind(self, captured_scopes: CapturedScopes, /) -> "Patcher[Never]":
        def empty_patch_generator() -> Iterator[Never]:
            return iter(())

        return FunctionPatcher(patch_generator=empty_patch_generator)


class SemigroupSymbol(ABC):
    """
    Marker base class for Symbols that return a Semigroup (both Merger and Patcher).

    Use ``isinstance(mixin, SemigroupSymbol)`` to check if a mixin returns
    an evaluator that is both Merger and Patcher (e.g., ``_ScopeSemigroup``).

    Currently, ``NestedSymbolMapping`` is the only subclass.
    """


@dataclass(kw_only=True, frozen=True, eq=False)
class NestedSymbolMapping(SemigroupSymbol, StaticSymbolMapping):
    """
    Non-empty dependency graph node corresponding to nested Scope definitions.

    Uses object.__eq__ and object.__hash__ (identity-based) for O(1) comparison.
    This works because interned graphs within the same outer are the same object.

    Implements ``Callable[[CapturedScopes], _ScopeSemigroup]`` to resolve resources
    from a lexical scope into a scope semigroup.

    Inherits ``HasDict`` via ``StaticSymbolMapping`` to enable ``@cached_property``
    (which requires ``__dict__``) in a slots-based dataclass.

    Subclasses
    ==========

    - ``SyntheticSymbolMapping``: For synthetic mixins (no local definition, only inherited)
    - ``DefinedSymbolMapping``: For defined mixins (has local definition with extend references)

    Conceptual Layer Distinction
    ============================

    **Important**: This class is a **Symbol** (IS-A Mapping), not a Semigroup.

    - ``NestedSymbolMapping`` is a **Symbol layer** concept: a Mapping containing nested resources
    - ``_ScopeSemigroup`` is an **Evaluator layer** concept: returned by ``__call__``

    The name ``NestedSymbolMapping`` is retained because it IS-A Mapping (contains nested
    resources). ``_ScopeSemigroup`` is a type of Evaluator that implements both ``Merger``
    and ``Patcher`` interfaces.

    ``__call__`` Semantics
    ======================

    ``__call__`` returns ``_ScopeSemigroup``, which implements both ``Merger`` and ``Patcher``
    interfaces. This allows nested Scopes to simultaneously act as:

    - **Merger**: Merge nested Scopes with the same name from multiple base classes
    - **Patcher**: Extend existing nested Scopes

    Compile-time Index Data Structures
    ===================================

    To support JIT and Proxy optimization, the following ``@cached_property`` need to be added:

    ``merger_base_indices``
    -----------------------

    ::

        @cached_property
        def merger_base_indices(self) -> Mapping[NestedMergerSymbol, NestedSymbolIndex]:
            '''Filter linearized_base_indices to keep only NestedMergerSymbol.

            Use case: JIT/Proxy can directly access all pure Merger base classes without runtime isinstance checks.
            '''
            return {
                base: index
                for base, index in self.linearized_base_indices.items()
                if isinstance(base, NestedMergerSymbol)
            }

    ``patcher_base_indices``
    ------------------------

    ::

        @cached_property
        def patcher_base_indices(self) -> Mapping[NestedPatcherSymbol, NestedSymbolIndex]:
            '''Filter linearized_base_indices to keep only NestedPatcherSymbol.

            Use case: JIT/Proxy can directly access all pure Patcher base classes without runtime isinstance checks.
            '''
            return {
                base: index
                for base, index in self.linearized_base_indices.items()
                if isinstance(base, NestedPatcherSymbol)
            }

    ``mapping_base_indices``
    ------------------------

    ::

        @cached_property
        def mapping_base_indices(self) -> Mapping[NestedSymbolMapping, NestedSymbolIndex]:
            '''Filter linearized_base_indices to keep only NestedSymbolMapping.

            Use case: JIT/Proxy can directly access all Mapping base classes without runtime isinstance checks.
            '''
            return {
                base: index
                for base, index in self.linearized_base_indices.items()
                if isinstance(base, NestedSymbolMapping)
            }

    JIT Usage Example
    =================

    ::

        # JIT or Proxy can utilize typed indices for direct access
        for merger, index in scope.mixin.merger_base_indices.items():
            # No isinstance check needed, merger guaranteed to be NestedMergerSymbol
            evaluator = merger(captured_scopes)  # Return type is Merger

        for patcher, index in scope.mixin.patcher_base_indices.items():
            # No isinstance check needed, patcher guaranteed to be NestedPatcherSymbol
            evaluator = patcher(captured_scopes)  # Return type is Patcher

    NestedSymbolIndex Collaboration
    ===============================

    ``NestedSymbolIndex`` provides O(1) random access capability. For example::

        NestedSymbolIndex(primary_index=5, secondary_index=2)
        # Represents: tuple(outer.generate_strict_super())[5].definition[name].compile(outer, name)[2]

    Combined with typed indices, JIT can:

    1. Pre-generate code paths for accessing specific Mergers
    2. Pre-generate code paths for collecting all Patchers
    3. Eliminate runtime ``isinstance`` checks
    4. Use ``NestedSymbolIndex`` for O(1) random access instead of traversal

    .. todo::

        Add ``merger_base_indices``, ``patcher_base_indices``,
        ``mapping_base_indices`` properties.
    """

    def generate_strict_super(self):
        """
        Generate the strict super symbols (all direct and transitive bases, excluding self).

        .. todo::

            This method will be used with the new ``Scope.captured_scopes_sequence``
            (which replaces ``Scope.mixins``) via
            ``zip(mixin.generate_strict_super(), scope.captured_scopes_sequence)``.
        """
        return iter(self.linearized_base_indices.keys())

    outer: Final[SymbolMapping]
    key: Final[Hashable]

    @cached_property
    def base_indices(self) -> Mapping["NestedSymbolMapping", int]:
        """Collect base_indices from outer's strict super symbols."""
        return cast(
            Mapping["NestedSymbolMapping", int],
            _collect_base_indices(self.outer, self.key),
        )

    @cached_property
    def depth(self) -> int:
        """Compute depth in O(1) by leveraging outer's cached depth."""
        if isinstance(self.outer, NestedSymbolMapping):
            return self.outer.depth + 1
        return 1

    @cached_property
    def getter(self) -> Callable[[CapturedScopes], "Node"]:
        """Create getter function for accessing this nested scope."""
        index = self.depth - 1
        if isinstance(self.key, str):
            return _make_jit_getter(self.key, index)
        return lambda captured_scopes: captured_scopes[index][self.key]

    @cached_property
    def _linearized_outer_base_indices(
        self,
    ) -> Mapping["NestedSymbolMapping", NestedSymbolIndex]:
        """
        Index mapping for outer base classes (common to both subclasses).

        This includes:
        1. Outer base classes from ``self.base_indices``
        2. Strict super mixins from each outer base class's ``generate_strict_super()``

        Uses ``ChainMap`` to avoid dictionary unpacking. Outer base classes take
        precedence over their strict super symbols (first map in ChainMap wins on key collision).
        """
        outer_base_indices: dict["NestedSymbolMapping", NestedSymbolIndex] = {
            base: NestedSymbolIndex(
                primary_index=OuterBaseIndex(index=primary_index),
                secondary_index=SymbolIndexSentinel.OWN,
            )
            for base, primary_index in self.base_indices.items()
        }
        linearized_outer_base_indices: dict[
            "NestedSymbolMapping", NestedSymbolIndex
        ] = {
            cast("NestedSymbolMapping", linearized_base): NestedSymbolIndex(
                primary_index=OuterBaseIndex(index=primary_index),
                secondary_index=secondary_index,
            )
            for base, primary_index in self.base_indices.items()
            for secondary_index, linearized_base in enumerate(
                base.generate_strict_super()
            )
        }
        return ChainMap(outer_base_indices, linearized_outer_base_indices)

    @property
    @abstractmethod
    def linearized_base_indices(
        self,
    ) -> Mapping["NestedSymbolMapping", NestedSymbolIndex]:
        """
        Index mapping for all linearized base classes.

        This property maps all base classes (including direct and inherited base classes) to their
        ``NestedSymbolIndex``, supporting O(1) random access.

        Subclasses implement this to include/exclude extension references:
        - ``SyntheticSymbolMapping``: Returns only inherited base indices
        - ``DefinedSymbolMapping``: Returns inherited + extension base indices

        .. todo::

            Add typed index properties as filtered views of this property.

        .. todo::

            Exclude ``_SyntheticSymbol`` from this mapping. Synthetic mixins are placeholders
            for leaf resources that have no definition in the current scope (only inherited
            from base classes). They should not appear in the linearized base indices because
            they don't contribute any actual behavior.
        """

    @abstractmethod
    def bind(self, captured_scopes: CapturedScopes, /) -> "_ScopeSemigroup":
        """
        Resolve resources from the given lexical scope into a _ScopeSemigroup.

        This method creates a scope factory that:
        1. Creates a mixin from this definition's definition
        2. Includes mixins from any extended scopes (via extend references)
        3. Returns a _ScopeSemigroup that can merge with other scopes
        """


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class SyntheticSymbolMapping(_SyntheticSymbol, NestedSymbolMapping):
    """
    NestedSymbolMapping for synthetic symbols (no local definition).

    Synthetic mixins are created when a nested scope is inherited from base classes
    but has no local definition in the current scope. They use default ``CachedScope``
    and have no extend references.
    """

    @property
    def linearized_base_indices(
        self,
    ) -> Mapping[NestedSymbolMapping, NestedSymbolIndex]:
        """Return only inherited base indices (no extension references)."""
        return self._linearized_outer_base_indices

    def bind(self, captured_scopes: CapturedScopes, /) -> "_ScopeSemigroup":
        """Resolve resources using default CachedScope (no extend references)."""

        def scope_factory() -> StaticScope:
            assert (
                captured_scopes
            ), "captured_scopes must not be empty when resolving resources"
            return CachedScope(
                symbols={self: captured_scopes},
                symbol=self,
            )

        return _ScopeSemigroup(
            scope_factory=scope_factory,
            access_path_outer=self.outer,
            key=self.key,
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class DefinedSymbolMapping(_DefinedSymbol, NestedSymbolMapping):
    """
    NestedSymbolMapping for defined scopes (has local definition with extend references).

    Defined mixins are created when a nested scope has a local definition in the current
    scope. They use the scope class from the definition and include extend references.
    """

    definition: "_DefinitionMapping"  # type: ignore[assignment]  # Narrowing from base class

    @cached_property
    def _linearized_own_base_indices(
        self,
    ) -> dict[NestedSymbolMapping, NestedSymbolIndex]:
        """
        Linearized indices for own bases (extend references) and their strict super symbols.

        This includes:
        1. Direct extend references from ``self.definition.bases``
        2. Strict super mixins from each extend reference's ``generate_strict_super()``

        Uses ``OwnBaseIndex`` to distinguish from outer base indices.
        """
        result: dict[NestedSymbolMapping, NestedSymbolIndex] = {}
        for own_base_index, reference in enumerate(self.definition.bases):
            own_base = _resolve_symbol_reference(
                reference, self.outer, NestedSymbolMapping
            )
            # Direct extend reference
            result[own_base] = NestedSymbolIndex(
                primary_index=OwnBaseIndex(index=own_base_index),
                secondary_index=SymbolIndexSentinel.OWN,
            )
            # Linearized strict super symbols of the extend reference
            for linearized_index, linearized_base in enumerate(
                own_base.generate_strict_super()
            ):
                if (
                    linearized_base not in result
                ):  # Avoid overwriting more direct references
                    result[cast(NestedSymbolMapping, linearized_base)] = (
                        NestedSymbolIndex(
                            primary_index=OwnBaseIndex(index=own_base_index),
                            secondary_index=linearized_index,
                        )
                    )
        return result

    @property
    def linearized_base_indices(
        self,
    ) -> Mapping[NestedSymbolMapping, NestedSymbolIndex]:
        """
        Index mapping including own bases (extend references) and outer bases.

        Data Sources
        ============

        Indices consist of four parts:

        1. **Outer base classes**: From ``self.base_indices``,
           ``primary_index`` is ``OuterBaseIndex``, ``secondary_index`` is ``SymbolIndexSentinel.OWN``

        2. **Strict super mixins of outer bases**: From each outer base's ``generate_strict_super()``,
           ``primary_index`` is ``OuterBaseIndex``, ``secondary_index`` is ``int``

        3. **Own bases (extend references)**: From ``self.definition.bases``,
           ``primary_index`` is ``OwnBaseIndex``, ``secondary_index`` is ``SymbolIndexSentinel.OWN``

        4. **Strict super mixins of own bases**: From each extend reference's ``generate_strict_super()``,
           ``primary_index`` is ``OwnBaseIndex``, ``secondary_index`` is ``int``

        Uses ``ChainMap`` to avoid dictionary unpacking. Own bases take
        precedence over outer bases (first map in ChainMap wins on key collision).
        """
        return ChainMap(
            self._linearized_own_base_indices,
            cast(
                dict[NestedSymbolMapping, NestedSymbolIndex],
                self._linearized_outer_base_indices,
            ),
        )

    @override
    def bind(self, captured_scopes: CapturedScopes, /) -> "_ScopeSemigroup":
        """Resolve resources including extend references from definition."""

        def scope_factory() -> StaticScope:
            assert (
                captured_scopes
            ), "captured_scopes must not be empty when resolving resources"

            def generate_all_symbol_items() -> (
                Iterator[tuple[StaticSymbolMapping, CapturedScopes]]
            ):
                """
                Generate all mixin items for the scope, including:
                - CapturedScopes from this definition, keyed by scope's mixin
                - CapturedScopes from extended scopes, preserving their original keys
                """
                yield (self, captured_scopes)
                for reference in self.definition.bases:
                    extended_scope = _resolve_resource_reference(
                        reference=reference,
                        captured_scopes=captured_scopes,
                        forbid_instance_scope=True,
                    )
                    yield from extended_scope.symbols.items()

            return self.definition.scope_class(
                symbols=dict(generate_all_symbol_items()),
                symbol=self,
            )

        return _ScopeSemigroup(
            scope_factory=scope_factory,
            access_path_outer=self.outer,
            key=self.key,
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class InstanceSymbolMapping(SymbolMapping):
    """Non-empty dependency graph node for InstanceScope.

    Uses object.__eq__ and object.__hash__ (identity-based) for O(1) comparison.
    This works because interned graphs with equal head within the same outer
    are the same object.
    """

    prototype: Final[StaticSymbolMapping]
    """
    The static dependency graph that this instance is based on.
    """

    def generate_strict_super(self) -> Iterator[Symbol]:
        """
        Instance mixin has no strict super symbols.

        Instance mixins are leaf nodes that cannot merge with other mixins.
        """
        return iter(())

    def __iter__(self) -> Iterator[Hashable]:
        """Delegate to prototype."""
        return iter(self.prototype)

    def __len__(self) -> int:
        """Delegate to prototype."""
        return len(self.prototype)

    def __getitem__(self, key: Hashable) -> "Symbol":
        """Delegate to prototype."""
        return self.prototype[key]

    @property
    def depth(self) -> int:
        """Delegate to prototype."""
        return self.prototype.depth  # type: ignore[attr-defined]


Resource = NewType("Resource", object)


class Scope(Mapping[Hashable, "Node"], ABC):
    """
    A Scope represents resources available via attributes or keys.

    There are two types of scopes:

    - ``StaticScope``: Represents class/module level static definitions.
      Contains mixins and supports ``__call__`` to create instances.
    - ``InstanceScope``: Created via ``StaticScope.__call__``.
      Stores kwargs directly and delegates to base scope for other lookups.

    .. todo::
        Merge Scope/CachedScope/WeakCachedScope into a single class that provides 26 combinations
        of ResourceConfig behaviors on demand.

        Provide ResourceConfig configuration through new decorators. Note that this configuration
        is static, independent of Scope instances, and may be compiled into bytecode by Symbol in the future.
        ```
        @dataclass
        class BuilderDefinition:
            bind_captured_scopes: Callable[[CapturedScopes, str], Callable[[Scope, ResourceConfig], Evaluator]]
            config: ResourceConfig
            '''
            Default config is inferred from ``inspect.signature`` and can be modified by annotations
            '''

        ```


        Use the same Merger/Patcher interface to handle context managers/async, but the type of `TResult`
        depends on ResourceConfig and could be Awaitable/ContextManager/AsyncContextManager, or a direct
        synchronous type. The `TPatch` type of `@resource` also depends on ResourceConfig and could be
        `Endofunction`/`ContextManagerEndofunction`/`AsyncEndofunction`/`AsyncContextManagerEndofunction`.
        This means the same Merger/Patcher interface can handle synchronous/asynchronous/context manager cases.

    .. todo::
        Support defining methods, requiring dynamic class generation.

        The current implementation provides resources by intercepting attribute access via ``__getattr__``,
        but ``__getattr__`` is not a true method and cannot be used to define dunder methods (such as
        ``__str__``, ``__repr__``, ``__eq__``, etc.). Python's dunder method lookup happens directly
        in the class's ``__dict__`` and does not go through ``__getattr__``.

        Problem example::

            @scope()
            class MyScope:
                @resource
                def __str__() -> str:
                    return "custom string representation"

            root = mount(MyScope)
            str(root)  # Won't call custom __str__, uses Scope's default __str__ instead

    """

    @property
    @abstractmethod
    def symbols(
        self,
    ) -> Mapping[StaticSymbolMapping, CapturedScopes]:
        """The symbols that provide resources for this scope, keyed by symbol.

        Each scope's own properties (not from extend=) are stored at
        symbols[self.symbol]. Extended scopes contribute their symbols
        with their original symbol keys.

        .. todo:: Replace ``dict`` with ``ChainMap``.
        """
        ...

    symbol: "NestedSymbolMapping | InstanceSymbolMapping"
    """The runtime access path from root to this scope, in reverse order.

    This path reflects how the scope was accessed at runtime, not where
    it was statically defined. For example, root.object1.MyInner and
    root.object2.MyInner should have different symbols even if
    MyInner is defined in the same place.
    """

    def __getitem__(self, key: Hashable) -> "Node":
        def generate_resource() -> Iterator[Mixin]:
            for current_symbol, captured_scopes in self.symbols.items():
                try:
                    factory_or_patch = _symbol_getitem(
                        current_symbol, captured_scopes, key
                    )
                except KeyError:
                    continue
                yield factory_or_patch(self)

        return _evaluate_resource(resource_generator=generate_resource)

    def __getattr__(self, key: str) -> "Node":
        try:
            return self[key]
        except KeyError as e:
            raise AttributeError(name=key, obj=self) from e

    def __iter__(self) -> Iterator[Hashable]:
        visited: set[Hashable] = set()
        for current_symbol in self.symbols.keys():
            if isinstance(current_symbol, _SyntheticSymbol):
                # Synthetic symbols don't have their own keys
                continue
            assert isinstance(current_symbol, _DefinedSymbol)
            assert isinstance(current_symbol.definition, _DefinitionMapping)
            for key in current_symbol.definition.keys():
                if key not in visited:
                    visited.add(key)
                    yield key

    def __len__(self) -> int:
        return sum(1 for _ in self)

    @override
    def __dir__(self) -> Sequence[str]:
        """
        .. note:: This method uses the two-arg super() as a workaround for https://github.com/python/cpython/pull/124455
        """
        return (
            *(key for key in self if isinstance(key, str)),
            *super(Scope, self).__dir__(),
        )


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class StaticScope(Scope, ABC):
    """
    A static scope representing class/module level definitions.

    StaticScope stores symbols directly and supports ``__call__`` to create
    InstanceScope with additional kwargs.
    """

    symbols: Mapping[StaticSymbolMapping, CapturedScopes]  # type: ignore[misc]
    """
    .. todo::

        Delete this field and replace with ``captured_scopes_sequence: Sequence[CapturedScopes]``
        that is isomorphic to ``symbol.generate_strict_super()``.

        This enables:

        - Zip with ``generate_strict_super()`` to pair each Symbol with its CapturedScopes
        - O(1) random access outer scope using ``NestedSymbolIndex`` to construct
          ``Sequence[CapturedScopes]``
    """

    symbol: StaticSymbolMapping  # type: ignore[misc]

    def __call__(self, **kwargs: object) -> "InstanceScope":
        """
        Create an InstanceScope with the given kwargs.

        .. todo:: Phase 2: Pass ``symbol`` and ``base_symbols``
                  when creating ``InstanceSymbolMapping``.
        """
        return InstanceScope(
            base_scope=self,
            kwargs=kwargs,
            symbol=self.symbol.instance_symbol,
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class InstanceScope(Scope):
    """
    An instance scope created via StaticScope.__call__.

    InstanceScope stores kwargs directly and checks them first during lookup,
    then delegates to the base scope for other resources.

    .. note:: kwargs keys are bounded by str because Python's **kwargs only accepts string keys.
    """

    base_scope: Final[StaticScope]
    kwargs: Final[Mapping[str, object]]
    symbol: InstanceSymbolMapping  # type: ignore[misc]

    @property
    @override
    def symbols(
        self,
    ) -> Mapping[StaticSymbolMapping, CapturedScopes]:
        return self.base_scope.symbols

    @override
    def __getitem__(self, key: Hashable) -> Node:
        if isinstance(key, str) and key in self.kwargs:
            value = self.kwargs[key]

            def generate_resource() -> Iterator[Mixin]:
                # Yield the kwargs value as a Merger
                yield _EndofunctionMerger(base_value=cast(Resource, value))
                # Also collect any Patchers from symbols
                for current_symbol, captured_scopes in self.symbols.items():
                    try:
                        factory_or_patch = _symbol_getitem(
                            current_symbol, captured_scopes, key
                        )
                    except KeyError:
                        continue
                    yield factory_or_patch(self)

            return _evaluate_resource(resource_generator=generate_resource)
        return super(InstanceScope, self).__getitem__(key)

    @override
    def __iter__(self) -> Iterator[Hashable]:
        for key in self.kwargs:
            yield key
        for key in super(InstanceScope, self).__iter__():
            if key not in self.kwargs:
                yield key

    @override
    def __len__(self) -> int:
        return sum(1 for _ in self)


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class CachedScope(StaticScope):
    """A StaticScope with cached resource lookups."""

    _cache: MutableMapping[Hashable, "Node"] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @override
    def __getitem__(self, key: Hashable) -> "Node":
        """
        .. note:: This method uses the two-arg super() as a workaround for https://github.com/python/cpython/pull/124455
        """
        if key not in self._cache:
            value = super(CachedScope, self).__getitem__(key)
            self._cache[key] = value
            return value
        else:
            return self._cache[key]


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class WeakCachedScope(CachedScope):
    """A CachedScope with weak reference caching."""

    _cache: MutableMapping[Hashable, "Node"] = field(
        default_factory=WeakValueDictionary, init=False, repr=False, compare=False
    )


def _calculate_most_derived_class(first: type, *rest: type) -> type:
    """Calculate the most derived class."""

    candidates = (first,)
    for new_candidate in rest:
        if any(issubclass(candidate, new_candidate) for candidate in candidates):
            continue
        else:
            candidates = (
                *(
                    candidate
                    for candidate in candidates
                    if not issubclass(new_candidate, candidate)
                ),
                new_candidate,
            )

    match candidates:
        case (winner,):
            return winner
        case _:
            raise TypeError(
                "class conflict: "
                "the class of a derived class "
                "must be a (non-strict) subclass "
                "of the classes of all its bases"
            )


CapturedScopes: TypeAlias = Sequence[Scope]
"""
A sequence of scopes representing the lexical scope, starting from the outermost scope to the innermost scope.
"""


Node: TypeAlias = Resource | Scope


class Merger(Generic[TPatch_contra, TResult_co], ABC):
    @abstractmethod
    def create(self, patches: Iterator[TPatch_contra]) -> TResult_co: ...


class Patcher(Iterable[TPatch_co], ABC):
    """
    An Patcher provides extra data to be applied to a Node created by a ``Merger``.
    """


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FunctionPatcher(Patcher[TPatch_co]):
    patch_generator: Callable[[], Iterator[TPatch_co]]

    def __iter__(self) -> Iterator[TPatch_co]:
        return self.patch_generator()


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FunctionMerger(Merger[TPatch_contra, TResult_co]):
    """Merger that applies custom aggregation function to patches."""

    aggregation_function: Callable[[Iterator[TPatch_contra]], TResult_co]

    @override
    def create(self, patches: Iterator[TPatch_contra]) -> TResult_co:
        return self.aggregation_function(patches)


TScope = TypeVar("TScope", bound=StaticScope)


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _EndofunctionMerger(
    Generic[TResult], Merger[Callable[[TResult], TResult], TResult]
):
    """Merger that applies patches as endofunctions via reduce."""

    base_value: TResult

    @override
    def create(self, patches: Iterator[Callable[[TResult], TResult]]) -> TResult:
        return reduce(lambda acc, endo: endo(acc), patches, self.base_value)


def _symbol_getitem(
    symbol_mapping: StaticSymbolMapping,
    captured_scopes: CapturedScopes,
    key: Hashable,
    /,
) -> Callable[[Scope], Mixin]:
    """
    Get a factory function from a dependency graph by key.

    Uses ``symbol_mapping[key]`` to get the NestedSymbol (which IS-A MixinGetter),
    then creates a closure that calls ``bind`` with the captured scopes.
    """
    nested_symbol = symbol_mapping[key]

    def bind_scope(scope: Scope) -> Mixin:
        inner_captured_scopes: CapturedScopes = (*captured_scopes, scope)
        mixin_result = cast(MixinGetter[Mixin], nested_symbol).bind(
            inner_captured_scopes
        )
        # If mixin_result is a _ScopeSemigroup, set access_path_outer to the scope's symbol
        if isinstance(mixin_result, _ScopeSemigroup):
            return replace(mixin_result, access_path_outer=scope.symbol)
        return mixin_result

    return bind_scope


def _collect_base_indices(
    outer_symbol: "SymbolMapping", key: Hashable, /
) -> Mapping["NestedSymbol", int]:
    """Collect base_indices from outer_symbol's strict super symbols."""
    return {
        cast("NestedSymbol", item_symbol): index
        for index, base in enumerate(
            cast(Iterator["SymbolMapping"], outer_symbol.generate_strict_super())
        )
        if (item_symbol := base.get(key)) is not None
    }


def _evaluate_resource(
    resource_generator: Callable[[], Iterator[Mixin]],
) -> Node:
    """
    Evaluate a resource by selecting a Merger and applying Patches.

    Algorithm for selecting the Merger:
    1. If there is exactly one item that is a Merger but NOT a Patch (pure Merger),
       it is selected as the Merger. All other items (including those that are both)
       are treated as Patches.
    2. If there are multiple pure Mergers, a ValueError is raised.
    3. If there are no pure Mergers, but there are items that are both Merger and Patch:
       One is arbitrarily selected as the Merger, and the rest are treated as Patches.
       (This assumes the semantics of these items satisfy commutativity).
    4. If there are no Mergers (pure or dual), a NotImplementedError is raised.
    """
    items = tuple(resource_generator())
    if not items:
        raise KeyError("No resource found")

    pure_mergers = [
        item
        for item in items
        if isinstance(item, Merger) and not isinstance(item, Patcher)
    ]
    dual_items = [
        item for item in items if isinstance(item, Merger) and isinstance(item, Patcher)
    ]
    pure_patches = [
        item
        for item in items
        if not isinstance(item, Merger) and isinstance(item, Patcher)
    ]

    selected_merger: Merger
    patches_to_apply: list[Patcher]

    if len(pure_mergers) == 1:
        selected_merger = pure_mergers[0]
        # Dual items are treated as patches here
        patches_to_apply = cast(list[Patcher], dual_items) + pure_patches
    elif len(pure_mergers) > 1:
        raise ValueError("Multiple Factory definitions provided")
    else:
        # No pure mergers
        if not dual_items:
            raise NotImplementedError("No Factory definition provided")

        # Pick one dual item as merger
        selected_merger = dual_items[0]
        # Remaining dual items are patches
        patches_to_apply = cast(list[Patcher], dual_items[1:]) + pure_patches

    # Flatten the patches
    flat_patches = (
        patch_content
        for patch_container in patches_to_apply
        for patch_content in patch_container
    )

    return selected_merger.create(flat_patches)


class Definition(ABC):
    @abstractmethod
    def compile(self, outer: SymbolMapping, key: str, /) -> Symbol:
        """
        Compile this definition into a Symbol for the given outer SymbolMapping.

        :param outer: The parent SymbolMapping that will contain this Symbol.
        :param key: The key/name for this resource in the parent mapping.
        :return: A Symbol instance ready for evaluation.
        """
        raise NotImplementedError()


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class MergerDefinition(Definition, Generic[TPatch_contra, TResult_co]):
    is_eager: bool = False
    is_local: bool = False

    @abstractmethod
    def compile(self, outer: SymbolMapping, key: str, /) -> NestedSymbol:
        raise NotImplementedError()


class PatcherDefinition(Definition, Generic[TPatch_co]):
    @abstractmethod
    def compile(self, outer: SymbolMapping, key: str, /) -> NestedSymbol:
        raise NotImplementedError()


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _MergerDefinition(MergerDefinition[TPatch_contra, TResult_co]):
    """Definition for merge decorator."""

    function: Callable[..., Callable[[Iterator[TPatch_contra]], TResult_co]]

    def compile(
        self, outer: SymbolMapping, key: str, /
    ) -> "_NestedMergerSymbol[TPatch_contra, TResult_co]":
        return _NestedMergerSymbol(
            key=key,
            outer=outer,
            definition=self,
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _ResourceDefinition(
    Generic[TResult], MergerDefinition[Callable[[TResult], TResult], TResult]
):
    """Definition for resource decorator."""

    function: Callable[..., TResult]

    def compile(
        self, outer: SymbolMapping, key: str, /
    ) -> "_NestedResourceSymbol[TResult]":
        return _NestedResourceSymbol(
            key=key,
            outer=outer,
            definition=self,
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _SinglePatchDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patch decorator (single patch)."""

    function: Callable[..., TPatch_co]

    def compile(
        self, outer: SymbolMapping, key: str, /
    ) -> "_NestedSinglePatchSymbol[TPatch_co]":
        return _NestedSinglePatchSymbol(
            key=key,
            outer=outer,
            definition=self,
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _MultiplePatchDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patches decorator (multiple patches)."""

    function: Callable[..., Iterable[TPatch_co]]

    def compile(
        self, outer: SymbolMapping, key: str, /
    ) -> "_NestedMultiplePatchSymbol[TPatch_co]":
        return _NestedMultiplePatchSymbol(
            key=key,
            outer=outer,
            definition=self,
        )


DefinitionMapping: TypeAlias = Mapping[
    str, Callable[[CapturedScopes], Callable[[Scope], Mixin]]
]


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _ScopeSemigroup(Merger[StaticScope, StaticScope], Patcher[StaticScope]):
    """
    Semigroup for merging Scope instances from extended scopes.

    .. todo:: Change to only support merging ``StaticScope``, prohibit merging ``InstanceScope``.

        The type signature should be changed to ``Merger[StaticScope, StaticScope]``, and add
        assertions in the ``create`` method to ensure ``InstanceScope`` is not passed in.
    """

    scope_factory: Final[Callable[[], StaticScope]]
    access_path_outer: Final[SymbolMapping]
    key: Final[Hashable]

    @override
    def create(self, patches: Iterator[StaticScope]) -> StaticScope:
        """
        Create a merged Scope from factory and patches.

        .. todo:: Phase 9: Replace ``generate_all_symbol_items`` with ``ChainMap``.
        """

        def all_scopes() -> Iterator[StaticScope]:
            yield from self
            return (yield from patches)

        scopes_tuple = tuple(all_scopes())
        match scopes_tuple:
            case (single_scope,) if (
                isinstance(single_scope.symbol, NestedSymbolMapping)
                and single_scope.symbol.outer == self.access_path_outer
            ):
                current_symbol = single_scope.symbol
            case ():
                raise AssertionError(" at least one scope expected")
            case _:
                # Get symbol via __getitem__. The symbol should always exist because
                # _ScopeSemigroup is created by NestedSymbolMapping.bind which
                # passes access_path_outer=self.outer and key=self.key. That
                # NestedSymbolMapping is stored in self.outer.intern_pool[self.key],
                # so __getitem__ will find it via intern_pool lookup.
                current_symbol = self.access_path_outer[self.key]
                assert isinstance(current_symbol, NestedSymbolMapping)

        winner_class = _calculate_most_derived_class(*(type(p) for p in scopes_tuple))

        def generate_all_symbol_items() -> (
            Iterator[tuple[StaticSymbolMapping, CapturedScopes]]
        ):
            for scope in scopes_tuple:
                yield from scope.symbols.items()

        all_symbol_items = list(generate_all_symbol_items())
        merged_symbols = dict(all_symbol_items)
        _logger.debug(
            "scopes_count=%(scopes_count)d "
            "total_symbol_items=%(total_symbol_items)d "
            "unique_after_dict=%(unique_after_dict)d",
            {
                "scopes_count": len(scopes_tuple),
                "total_symbol_items": len(all_symbol_items),
                "unique_after_dict": len(merged_symbols),
            },
        )

        return winner_class(
            symbols=merged_symbols,
            symbol=current_symbol,
        )

    @override
    def __iter__(self) -> Iterator[StaticScope]:
        scope = self.scope_factory()
        assert isinstance(
            scope, StaticScope
        ), f"scope must be StaticScope, got {type(scope)}"
        yield scope


TSymbol = TypeVar("TSymbol", bound=Symbol)


def _resolve_symbol_reference(
    reference: "ResourceReference[Hashable]",
    starting_symbol: "SymbolMapping",
    expected_type: type[TSymbol],
) -> TSymbol:
    """
    Resolve a ResourceReference to a Symbol using the given symbol as starting point.

    This is the compile-time analog of :func:`_resolve_resource_reference`. Instead of
    traversing Scope objects at runtime, it traverses SymbolMapping objects at compile-time.

    For RelativeReference:
        - Navigate up `levels_up` levels from the given symbol via ``.outer``
        - Then navigate down through ``path`` using ``symbol[key]``

    For AbsoluteReference:
        - Start from the root symbol (traverse up via ``.outer`` until reaching root)
        - Navigate down through ``path`` using ``symbol[key]``

    :param reference: The reference describing the path to the target symbol.
    :param starting_symbol: The starting symbol for relative references.
    :param expected_type: The expected type of the resolved symbol.
    :return: The resolved symbol of the expected type.
    :raises ValueError: If navigation goes beyond the root symbol.
    :raises TypeError: If intermediate or final resolved value is not of expected type.
    """
    match reference:
        case RelativeReference(levels_up=levels_up, path=parts):
            current: SymbolMapping = starting_symbol
            for level in range(levels_up):
                if not isinstance(current, NestedSymbolMapping):
                    raise ValueError(
                        f"Cannot navigate up {levels_up} levels: "
                        f"reached {type(current).__name__} (no outer) at level {level}"
                    )
                current = current.outer
        case AbsoluteReference(path=parts):
            # Navigate to root
            current = starting_symbol
            while isinstance(current, NestedSymbolMapping):
                current = current.outer
        case _ as unreachable:
            assert_never(unreachable)

    # Navigate through parts
    for part_index, part in enumerate(parts):
        resolved = current[part]
        if not isinstance(resolved, SymbolMapping):
            path_so_far = ".".join(str(p) for p in parts[: part_index + 1])
            raise TypeError(
                f"Expected SymbolMapping while resolving reference, "
                f"got {type(resolved).__name__} at part '{part}' "
                f"(path: {path_so_far})"
            )
        current = resolved

    if not isinstance(current, expected_type):
        raise TypeError(
            f"Final resolved symbol is not {expected_type.__name__}: "
            f"got {type(current).__name__}"
        )
    return current


def _resolve_resource_reference(
    reference: "ResourceReference[Hashable]",
    captured_scopes: CapturedScopes,
    forbid_instance_scope: bool = False,
) -> Scope:
    """
    Resolve a ResourceReference to a Scope using the given lexical scope.

    For RelativeReference:
        - Navigate up `levels_up` levels from the innermost scope
        - Then navigate down through `parts` by accessing attributes

    For AbsoluteReference:
        - Start from the root (outermost scope)
        - Navigate down through `parts` by accessing attributes

    :param forbid_instance_scope: If True, raises TypeError if any step in the
        path resolves to an InstanceScope. Used by extend to prevent referencing
        paths through InstanceScope (e.g., object1.MyInner where object1 is an
        InstanceScope).

    .. seealso:: :func:`_resolve_symbol_reference` for the compile-time analog that
                 traverses SymbolMapping objects instead of Scope objects.
    """
    match reference:
        case RelativeReference(levels_up=levels_up, path=parts):
            if levels_up > len(captured_scopes):
                raise ValueError(
                    f"Cannot navigate {levels_up} levels up from scope of depth {len(captured_scopes)}"
                )
            # Navigate up: levels_up=0 means innermost (last), levels_up=1 means outer, etc.
            scope_index = len(captured_scopes) - 1 - levels_up
            current: Scope | Resource = captured_scopes[scope_index]
        case AbsoluteReference(path=parts):
            if not captured_scopes:
                raise ValueError(
                    "Cannot resolve absolute reference with empty lexical scope"
                )
            current = captured_scopes[0]
        case _ as unreachable:
            assert_never(unreachable)

    # Navigate through parts
    traversed_parts: list[Hashable] = []
    for part in parts:
        resolved = current[part]
        if not isinstance(resolved, Scope):
            raise TypeError(
                f"Expected Scope while resolving reference, got {type(resolved)} at part '{part}'"
            )
        traversed_parts.append(part)
        if forbid_instance_scope and isinstance(resolved, InstanceScope):
            raise TypeError(
                f"Cannot extend through InstanceScope. "
                f"Path {'.'.join(str(p) for p in traversed_parts)} resolved to an InstanceScope."
            )
        current = resolved

    if not isinstance(current, Scope):
        raise TypeError(f"Final resolved value is not a Scope: {type(current)}")
    return current


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _DefinitionMapping(
    Mapping[Hashable, Definition],
    Definition,
):
    """Base class for scope definitions that create Scope instances from underlying objects."""

    scope_class: type[StaticScope]
    underlying: object
    bases: tuple["ResourceReference[Hashable]", ...] = ()

    def __iter__(self) -> Iterator[Hashable]:
        for name in dir(self.underlying):
            try:
                val = getattr(self.underlying, name)
            except AttributeError:
                continue
            if isinstance(val, Definition):
                yield name

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __getitem__(self, key: Hashable) -> Definition:
        """Get a Definition by key name.

        Raises KeyError if the key does not exist or the value is not a Definition.
        """
        try:
            val = getattr(self.underlying, cast(str, key))
        except AttributeError as error:
            raise KeyError(key) from error
        if not isinstance(val, Definition):
            raise KeyError(key)
        return val

    def compile(self, outer: SymbolMapping, key: str, /) -> "DefinedSymbolMapping":
        """
        Compile this definition mapping into a DefinedSymbolMapping.

        :param outer: The parent SymbolMapping that will contain this Symbol.
        :param key: The key/name for this scope in the parent mapping.
        :return: A DefinedSymbolMapping instance ready for evaluation.
        """
        nested_symbol_mapping = DefinedSymbolMapping(
            outer=outer,
            definition=self,
            key=key,
        )
        _logger.debug(
            "key=%(key)r underlying=%(underlying)r outer_key=%(outer_key)r",
            {
                "key": key,
                "underlying": self.underlying,
                "outer_key": getattr(outer, "key", "ROOT"),
            },
        )
        return nested_symbol_mapping


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _PackageDefinitionMapping(_DefinitionMapping):
    """A definition for packages that discovers submodules via pkgutil."""

    get_module_scope_class: Callable[[ModuleType], type[StaticScope]]
    underlying: ModuleType

    def __iter__(self) -> Iterator[Hashable]:
        yield from super(_PackageDefinitionMapping, self)

        for mod_info in pkgutil.iter_modules(self.underlying.__path__):
            yield mod_info.name

    @override
    def __getitem__(self, key: Hashable) -> Definition:
        """Get a Definition by key name, including lazily imported submodules."""
        # 1. Try parent (attributes that are Definition)
        try:
            return super(_PackageDefinitionMapping, self).__getitem__(key)
        except KeyError:
            pass

        # 2. Import submodule
        full_name = f"{self.underlying.__name__}.{key}"
        try:
            spec = importlib.util.find_spec(full_name)
        except ImportError as error:
            raise KeyError(key) from error

        if spec is None:
            raise KeyError(key)

        submod = importlib.import_module(full_name)

        # Create and return definition
        if hasattr(submod, "__path__"):
            return _PackageDefinitionMapping(
                underlying=submod,
                scope_class=self.get_module_scope_class(submod),
                get_module_scope_class=self.get_module_scope_class,
            )
        else:
            return _DefinitionMapping(
                underlying=submod,
                scope_class=self.get_module_scope_class(submod),
            )


def scope(
    *,
    scope_class: type[StaticScope] = CachedScope,
    bases: Iterable["ResourceReference[Hashable]"] = (),
) -> Callable[[object], _DefinitionMapping]:
    """
    Decorator that converts a class into a NamespaceDefinition.
    Nested classes MUST be decorated with @scope() to be included as sub-scopes.

    Note: Always use @scope() with parentheses, not @scope without parentheses.

    :param scope_class: The Scope subclass to use for this scope.
    :param extend: ResourceReferences to other scopes whose mixins should be included.
                   This allows composing scopes without explicit merge operations.

    Example - Using extend to inherit from another scope::

        @scope(extend=(
            RelativeReference(levels_up=1, path=("Base",)),
        ))
        class MyScope:
            @patch
            def foo() -> Callable[[int], int]:
                return lambda x: x + 1

    Example - Union mounting multiple scopes across modules::

        Multiple ``@scope()`` definitions with the same name are automatically merged
        as semigroups. This is the recommended way to create union mount points::

            # In branch0.py:
            @scope()
            class union_mount_point:
                pass  # Base empty scope

            # In branch1.py:
            @scope()
            class union_mount_point:
                @resource
                def foo() -> str:
                    return "foo"

            # In branch2.py:
            @scope()
            class union_mount_point:
                @extern
                def foo() -> str: ...

                @resource
                def bar(foo: str) -> str:
                    return f"{foo}_bar"

            # In main.py:
            root = mount(branch0, branch1, branch2)
            root.union_mount_point.foo  # "foo"
            root.union_mount_point.bar  # "foo_bar"

    """
    extend_tuple = tuple(bases)

    def wrapper(c: object) -> _DefinitionMapping:
        return _DefinitionMapping(
            underlying=c,
            scope_class=scope_class,
            bases=extend_tuple,
        )

    return wrapper


def _parse_package(
    module: ModuleType,
    get_module_scope_class: Callable[[ModuleType], type[StaticScope]],
) -> _DefinitionMapping:
    """
    Parses a module into a NamespaceDefinition.

    Only module-level attributes explicitly decorated with @resource, @patch, @patch_many, or @merge are included.
    Nested modules and packages are recursively parsed with lazy loading.

    IMPORTANT: Bare callables (without decorators) are NOT automatically included.
    Users must explicitly mark all injectable definitions with appropriate decorators.

    For packages (modules with __path__), uses pkgutil.iter_modules to discover submodules
    and importlib.import_module to lazily import them when accessed.
    """
    scope_class = get_module_scope_class(module)
    if hasattr(module, "__path__"):
        return _PackageDefinitionMapping(
            underlying=module,
            scope_class=scope_class,
            get_module_scope_class=get_module_scope_class,
        )
    return _DefinitionMapping(underlying=module, scope_class=scope_class)


Endofunction = Callable[[TResult], TResult]
ContextManagerEndofunction = Callable[[TResult], "ContextManager[TResult]"]
AsyncEndofunction = Callable[[TResult], Awaitable[TResult]]
AsyncContextManagerEndofunction = Callable[[TResult], "AsyncContextManager[TResult]"]


def merge(
    callable: Callable[..., Callable[[Iterator[TPatch_contra]], TResult_co]],
) -> MergerDefinition[TPatch_contra, TResult_co]:
    """
    A decorator that converts a callable into a merger definition with a custom aggregation strategy for patches.

    Example:

    The following example defines an merge that deduplicates strings from multiple patches into a frozenset.
        # In branch0.py:

        from mixinject import merge
        @merge
        def deduplicated_tags():
            return frozenset[str]

    Now, when multiple patches provide tags, they will be aggregated into a frozenset without duplicates.

        # In branch1.py:
        @patch
        def deduplicated_tags():
            return "tag1"

        # In branch1.py:
        @resource
        def another_dependency() -> str:
            return "dependency_value"

        # In branch2.py:
        @patch
        def deduplicated_tags(another_dependency):
            return f"tag2_{another_dependency}"

        # In main.py:
        import branch0
        import branch1
        import branch2
        root = mount(branch0, branch1, branch2)
        root.deduplicated_tags  # frozenset(("tag1", "tag2_dependency_value"))

    Note: For union mounting multiple scopes, use ``@scope()`` semigroups instead.
    See :func:`scope` for examples.
    """
    return _MergerDefinition(function=callable)


def patch(
    callable: Callable[..., TPatch_co],
) -> PatcherDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return _SinglePatchDefinition(function=callable)


def patch_many(
    callable: Callable[..., Iterable[TPatch_co]],
) -> PatcherDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return _MultiplePatchDefinition(function=callable)


def extern(callable: Callable[..., Any]) -> PatcherDefinition[Any]:
    """
    A decorator that marks a callable as an external resource.

    This is syntactic sugar equivalent to :func:`patch_many` returning an empty collection.
    It registers the resource name in the lexical scope without providing any patches,
    making it clear that the value should come from injection from an outer lexical scope
    via :class:`InstanceScope` or :meth:`StaticScope.__call__`.

    The decorated callable may have parameters for dependency injection, which will be
    resolved from the lexical scope when the resource is accessed. However, the callable's
    return value is ignored.

    Example::

        @extern
        def database_url(): ...

        # Equivalent to:
        @patch_many
        def database_url():
            return ()

    This pattern is useful for:

    - **Configuration parameters**: Declare dependencies without providing values
    - **Dependency injection**: Mark injection points for external values
    - **Module decoupling**: Declare required resources without hardcoding

    :param callable: A callable that may have parameters for dependency injection.
                     The return value is ignored.
    :return: A PatcherDefinition that provides no patches.
    """
    sig = signature(callable)

    def empty_patches_provider(**_kwargs: Any) -> Iterable[Any]:
        return ()

    empty_patches_provider.__signature__ = sig  # type: ignore[attr-defined]

    return _MultiplePatchDefinition(function=empty_patches_provider)


def resource(
    callable: Callable[..., TResult],
) -> MergerDefinition[Endofunction[TResult], TResult]:
    """
    A decorator that converts a callable into a merger definition that treats patches as endofunctions.

    It's a syntactic sugar for using ``merge`` with a standard endofunction application strategy.

    Example:
    The following example defines a resource that can be modified by patches.
        from mixinject import resource, patch
        @resource
        def greeting() -> str:
            return "Hello"


        @patch
        def enthusiastic_greeting() -> Endofunction[str]:
            return lambda original: original + "!!!"

    Alternatively, ``greeting`` can be defined with an explicit merge:
        from mixinject import merge
        @merge
        def greeting() -> Callable[[Iterator[Endofunction[str]]], str]:
            return lambda endos: reduce(
                (lambda original, endo: endo(original)),
                endos,
                "Hello"
            )
    """
    return _ResourceDefinition(function=callable)


TMergerDefinition = TypeVar("TMergerDefinition", bound=MergerDefinition[Any, Any])


def eager(definition: TMergerDefinition) -> TMergerDefinition:
    """
    Decorator to mark a MergerDefinition as eager.

    Eager resources are evaluated immediately when the scope is accessed,
    rather than being lazily evaluated on first use.

    Example::

        @eager
        @resource
        def config() -> dict:
            return load_config()  # Loaded immediately

    :param definition: A MergerDefinition to mark as eager.
    :return: A new MergerDefinition with is_eager=True.
    """
    return replace(definition, is_eager=True)


def local(definition: TMergerDefinition) -> TMergerDefinition:
    """
    Decorator to mark a resource as local.

    Local resources are intermediate values, served as dependencies of other resources in the same scope.
    They are inaccessible from neither child scopes via dependency injection nor from getattr/getitem access.
    Example::

        @local
        @resource
        def api_endpoint() -> str:
            return "/api/v1"

    :param definition: A MergerDefinition to mark as local.
    :return: A new MergerDefinition with is_local=True.
    """
    return replace(definition, is_local=True)


def evaluate(
    namespace: ModuleType | _DefinitionMapping,
) -> StaticScope:
    """
    Resolves a Scope from the given object using the provided lexical scope.

    :param namespace: Module or namespace definition (decorated with @scope) to resolve resources from.
    :return: An instance of the cls type with resolved mixins.

    Example::

        root = mount(MyNamespace)

    .. todo:: Phase 2: Pass ``symbol`` and ``base_symbols``
              when creating ``NestedSymbolMapping``.
    """
    captured_scopes: CapturedScopes = ()
    root_scope_class: type[StaticScope] = CachedScope

    def get_module_scope_class(_module: ModuleType) -> type[StaticScope]:
        return CachedScope

    namespace_definition: _DefinitionMapping
    if isinstance(namespace, _DefinitionMapping):
        namespace_definition = namespace
    elif isinstance(namespace, ModuleType):
        namespace_definition = _parse_package(
            namespace,
            get_module_scope_class=get_module_scope_class,
        )
    else:
        assert_never(namespace)

    root_symbol = RootSymbolMapping(
        definition=namespace_definition,
    )
    return root_scope_class(
        symbols={root_symbol: captured_scopes},
        symbol=root_symbol,
    )


def _make_jit_getter(name: str, index: int) -> Callable[[CapturedScopes], "Node"]:
    """Create a factory that retrieves a resource from lexical scope using JIT-compiled attribute access."""
    # lambda captured_scopes: captured_scopes[index].{name}
    lambda_node = ast.Lambda(
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="captured_scopes")],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=ast.Attribute(
            value=ast.Subscript(
                value=ast.Name(id="captured_scopes", ctx=ast.Load()),
                slice=ast.Constant(value=index),
                ctx=ast.Load(),
            ),
            attr=name,
            ctx=ast.Load(),
        ),
    )
    module_node = ast.Expression(body=lambda_node)
    ast.fix_missing_locations(module_node)
    code = compile(module_node, filename="<mixinject__make_jit_factory>", mode="eval")
    # No globals needed for this simple lambda
    return eval(code, {})


def _find_param_in_symbol_chain(
    param_name: str, starting_symbol: SymbolMapping
) -> "NestedSymbol | NestedSymbolMapping":
    """
    Find a parameter in the symbol chain (lexical scope + extends).

    Traverses up the outer chain to find the parameter. Each symbol's __getitem__
    handles extends resolution, so we only need to traverse the lexical scope chain.

    :param param_name: The name of the parameter to find.
    :param starting_symbol: The starting SymbolMapping to search from.
    :return: The NestedSymbol (for leaf resources) or NestedSymbolMapping (for scopes).
    :raises KeyError: If the parameter is not found in the symbol chain.
    """
    current: SymbolMapping = starting_symbol
    while True:
        if param_name in current:
            param_symbol = current[param_name]
            assert isinstance(
                param_symbol, (NestedSymbol, NestedSymbolMapping)
            ), f"Parameter '{param_name}' resolved to unexpected symbol type: {type(param_symbol)}"
            return param_symbol
        if isinstance(current, NestedSymbolMapping):
            current = current.outer
        else:
            raise KeyError(f"Parameter '{param_name}' not found in symbol chain")


def _is_param_in_symbol_chain(param_name: str, starting_symbol: SymbolMapping) -> bool:
    """Check if a parameter is resolvable from the symbol chain."""
    current: SymbolMapping = starting_symbol
    while True:
        if param_name in current:
            return True
        if isinstance(current, NestedSymbolMapping):
            current = current.outer
        else:
            return False


def _resolve_dependencies_jit_using_symbol(
    outer_symbol: SymbolMapping,
    function: Callable[P, T],
    name: str,
) -> Callable[[CapturedScopes], T]:
    """
    Resolve dependencies using the mixin chain.

    For each parameter p:
    1. param_symbol = _find_param_in_symbol_chain(p.name, outer_symbol)
    2. Use param_symbol.getter for JIT code generation

    This handles both extends (via SymbolMapping.__getitem__) and lexical scope
    (via traversing the outer chain).

    Special case: when param_name == name, starts search from outer_symbol.outer to
    avoid self-dependency, mimicking pytest fixture behavior.

    :param outer_symbol: The SymbolMapping containing the resource being resolved.
    :param function: The function for which to resolve dependencies.
    :param name: The name of the resource being resolved.
    :return: A wrapper function that takes captured scopes and returns the result.
    """
    sig = signature(function)
    params = tuple(sig.parameters.values())

    if not params:
        return lambda _captured_scopes: function()  # type: ignore

    # Check if first parameter is a positional-only scope parameter
    has_scope = False
    first_param = params[0]
    first_param_in_symbol = _is_param_in_symbol_chain(first_param.name, outer_symbol)
    if (first_param.kind == first_param.POSITIONAL_ONLY) or (
        first_param.kind == first_param.POSITIONAL_OR_KEYWORD
        and not first_param_in_symbol
    ):
        has_scope = True
        keyword_params = params[1:]
    else:
        keyword_params = params

    # Pre-fetch getters at compile time
    # For same-name parameters, start search from outer_symbol.outer to avoid self-dependency
    getters: list[Callable[[CapturedScopes], Node]] = []
    for parameter in keyword_params:
        if parameter.name == name:
            # Same-name dependency: start search from outer mixin's parent
            assert isinstance(
                outer_symbol, NestedSymbolMapping
            ), f"Same-name dependency '{name}' at root level is not allowed"
            param_symbol = _find_param_in_symbol_chain(
                parameter.name, outer_symbol.outer
            )
        else:
            # Normal dependency: resolve from outer_symbol chain
            param_symbol = _find_param_in_symbol_chain(parameter.name, outer_symbol)
        getters.append(param_symbol.getter)

    # Generate JIT code: function(captured_scopes[-1], param0=getters[0](cs), param1=getters[1](cs), ...)
    # Build keyword arguments
    keywords = []
    for index, parameter in enumerate(keyword_params):
        # Generates: getters[index](captured_scopes)
        value_expr = ast.Call(
            func=ast.Subscript(
                value=ast.Name(id="getters", ctx=ast.Load()),
                slice=ast.Constant(value=index),
                ctx=ast.Load(),
            ),
            args=[ast.Name(id="captured_scopes", ctx=ast.Load())],
            keywords=[],
        )
        keywords.append(ast.keyword(arg=parameter.name, value=value_expr))

    call_node = ast.Call(
        func=ast.Name(id="function", ctx=ast.Load()),
        args=(
            [
                ast.Subscript(
                    value=ast.Name(id="captured_scopes", ctx=ast.Load()),
                    slice=ast.Constant(value=-1),
                    ctx=ast.Load(),
                )
            ]
            if has_scope
            else []
        ),
        keywords=keywords,
    )

    lambda_node = ast.Lambda(
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="captured_scopes")],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=call_node,
    )

    module_node = ast.Expression(body=lambda_node)
    ast.fix_missing_locations(module_node)
    code = compile(
        module_node,
        filename="<mixinject__resolve_dependencies_jit_using_symbol>",
        mode="eval",
    )

    return eval(
        code,
        {
            "function": function,
            "getters": getters,
        },
    )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class AbsoluteReference(Generic[T]):
    """
    An absolute reference to a resource starting from the root scope.
    """

    path: Final[tuple[T, ...]]


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class RelativeReference(Generic[T]):
    """
    A reference to a resource relative to the current lexical scope.

    This is used to refer to resources in outer scopes.
    """

    levels_up: Final[int]
    """
    Number of levels to go up in the lexical scope.
    """

    path: Final[tuple[T, ...]]


ResourceReference: TypeAlias = AbsoluteReference[T] | RelativeReference[T]
"""
A reference to a resource in the lexical scope.

This is a union type of AbsoluteReference and RelativeReference.

.. todo:: (Optional) Add ``LexicalReference`` type.

    Add a third reference type that automatically finds the innermost scope containing the key::

        @final
        @dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
        class LexicalReference(Generic[T]):
            \"\"\"
            A lexical reference that automatically finds the innermost scope containing the key.

            Unlike RelativeReference which requires explicit levels_up,
            LexicalReference searches upward from the current scope until it finds
            a scope that contains the first element of the path.
            \"\"\"
            path: Final[tuple[T, ...]]

    Update ``_resolve_symbol_reference`` to support ``LexicalReference``.
"""


def resource_reference_from_pure_path(path: PurePath) -> ResourceReference[str]:
    """
    Parse a PurePath into a ResourceReference[str].

    Raises ValueError if the path is not normalized.
    A normalized path:
    - Has no '.' components (except a single '.' meaning current directory)
    - Has '..' only at the beginning (for relative paths)

    Examples:
        >>> resource_reference_from_pure_path(PurePath("../foo/bar"))
        RelativeReference(levels_up=1, path=('foo', 'bar'))
        >>> resource_reference_from_pure_path(PurePath("../../config"))
        RelativeReference(levels_up=2, path=('config',))
        >>> resource_reference_from_pure_path(PurePath("/absolute/path"))
        AbsoluteReference(path=('absolute', 'path'))
        >>> resource_reference_from_pure_path(PurePath("foo/../bar"))
        Traceback (most recent call last):
            ...
        ValueError: Path is not normalized: foo/../bar
    """
    if path.is_absolute():
        path_parts = path.parts[1:]
        for part in path_parts:
            if part == os.curdir or part == os.pardir:
                raise ValueError(f"Path is not normalized: {path}")
        return AbsoluteReference(path=path_parts)

    all_parts = path.parts

    if all_parts == (os.curdir,):
        return RelativeReference(levels_up=0, path=())

    levels_up = 0
    remaining_parts: list[str] = []
    finished_pardir = False

    for part in all_parts:
        if part == os.curdir:
            raise ValueError(f"Path is not normalized: {path}")
        elif part == os.pardir:
            if finished_pardir:
                raise ValueError(f"Path is not normalized: {path}")
            levels_up += 1
        else:
            finished_pardir = True
            remaining_parts.append(part)

    return RelativeReference(levels_up=levels_up, path=tuple(remaining_parts))

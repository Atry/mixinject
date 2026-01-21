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
    root.ignored_function  # AttributeError: 'StaticScope' object has no attribute 'ignored_function'

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

    @scope
    class Base:
        @resource
        def foo() -> str:
            return "base_foo"

    @scope
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

        @scope
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
    @scope
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
    @scope
    class Config:
        @extern
        def db_config(): ...

    outer_scope = mount(Config)(db_config={"host": "localhost", "port": "5432"})

    outer_scope: CapturedScopes = (outer_scope,)

    # Resources in modules can obtain this value via same-named parameter
    @scope
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


class PrototypeSymbolSentinel(Enum):
    """Sentinel value for symbols that are not instance symbols."""

    NOT_INSTANCE = auto()


class InstanceSymbolSentinel(Enum):
    """Sentinel value for instance_symbol when called on an already-instance symbol."""

    ALREADY_INSTANCE = auto()


TMixin_co = TypeVar("TMixin_co", bound="Mixin", covariant=True)


@dataclass(kw_only=True, frozen=True, eq=False)
class Symbol(
    ABC,
    Mapping[Hashable, "Symbol"],
    Generic[TMixin_co],
):
    """
    Base class for nodes in the dependency graph.

    All symbols support the Mapping interface (``__getitem__``, ``__iter__``, ``__len__``).
    Scope symbols have nested resources (len > 0), while leaf symbols have no items (len = 0).

    Conceptual Layer Distinction
    ============================

    This system has two distinct layers that should not be conflated:

    **Symbol Layer (Dependency Graph Nodes)**

    - ``Symbol``: Base class (all symbols are Mappings)
    - ``NestedScopeSymbol``: Scope Symbol with nested resources (len > 0)
    - ``NestedScopeSymbol``: Nested Scope Symbol (IS-A Mapping)

    **Evaluator Layer (Resource Evaluators)**

    - ``Evaluator = Merger | Patcher``
    - ``Merger``: Merges patches to produce result
    - ``Patcher``: Provides patches
    - ``_NestedMappingMixin``: An Evaluator that implements both Merger and Patcher

    **Relationship**

    - ``NestedMergerSymbol.__call__`` returns ``Merger``
    - ``NestedPatcherSymbol.__call__`` returns ``Patcher``
    - ``NestedScopeSymbol.__call__`` returns ``_NestedMappingMixin`` (an Evaluator)

    ``_NestedMappingMixin`` is currently the only Semigroup Evaluator, but the system
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

    1. **Compile-time type classification**: When creating Symbol in ``ScopeSymbol.__getitem__``,
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
        ├── ScopeSymbol (ABC, Mapping[Hashable, Symbol])
        │   │   __getitem__(key) → NestedMergerSymbol | NestedPatcherSymbol | NestedScopeSymbol
        │   │
        │   ├── Symbol (ABC)
        │   │   ├── RootScopeSymbol
        │   │   └── NestedScopeSymbol (IS-A Mapping, contains nested resources)
        │   │           __call__() → _NestedMappingMixin (an Evaluator: Merger ∩ Patcher)
        │   │           merger_base_indices: Mapping[NestedMergerSymbol, NestedSymbolIndex]
        │   │           patcher_base_indices: Mapping[NestedPatcherSymbol, NestedSymbolIndex]
        │   │           mapping_base_indices: Mapping[NestedScopeSymbol, NestedSymbolIndex]
        │   │
        │   └── InstanceScopeSymbol
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
    - ``NestedScopeSymbol.__call__`` → ``_NestedMappingMixin`` (an Evaluator: Merger ∩ Patcher)

    Definition Type to Symbol Type Mapping
    =====================================

    ========================== ========================== ============================
    Definition Type            Generated Symbol            ``get_evaluator`` Return Type
    ========================== ========================== ============================
    ``_MergerDefinition``      ``_NestedMergerSymbol``     ``Merger`` (not Patcher)
    ``_EndofunctionDefinition``    ``_EndofunctionSymbol``   ``Merger`` (not Patcher)
    ``_SinglePatchDefinition`` ``_NestedSinglePatchSymbol`` ``Patcher`` (not Merger)
    ``_MultiplePatchDefinition`` ``_NestedMultiplePatchSymbol`` ``Patcher`` (not Merger)
    ``_ScopeDefinition``     ``DefinedScopeSymbol``    ``_NestedMappingMixin`` (Evaluator)
    ========================== ========================== ============================

    .. todo:: Inherit from ``EvaluatorGetter``. Add ``@abstractmethod __call__``.
    """

    outer: Final["Symbol | OuterSentinel"]
    key: Final[Hashable | KeySentinel]
    prototype: Final["Symbol | PrototypeSymbolSentinel"] = (
        PrototypeSymbolSentinel.NOT_INSTANCE
    )
    intern_pool: Final[weakref.WeakValueDictionary[Hashable, "Symbol"]] = field(
        default_factory=weakref.WeakValueDictionary
    )

    @abstractmethod
    def bind(self, captured_scopes: "CapturedScopes", /) -> TMixin_co:
        """Retrieve the Mixin for the given captured scopes."""
        ...

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other: object) -> bool:
        return self is other

    def __iter__(self) -> Iterator[Hashable]:
        """Iterate over keys in this symbol.

        For scope symbols, yields keys from definition and bases.
        For leaf symbols, yields nothing (empty iterator).
        """
        seen: set[Hashable] = set()

        # Keys from self.definition (only if DefinedSymbol with _ScopeDefinition)
        if isinstance(self, DefinedSymbol):
            definition = self.definition
            if isinstance(definition, _ScopeDefinition):
                for key in definition:
                    if key not in seen:
                        seen.add(key)
                        yield key

        # Keys from bases
        for base in cast(Iterator["Symbol"], self.generate_strict_super()):
            for key in base:
                if key not in seen:
                    seen.add(key)
                    yield key

    def __len__(self) -> int:
        """Return the number of keys in this symbol."""
        return sum(1 for _ in self)

    def __getitem__(self, key: Hashable) -> "Symbol":
        """Get or create the child Symbol for the specified key.

        For scope symbols, compiles and caches nested symbols.
        For leaf symbols, raises KeyError.
        """
        existing = self.intern_pool.get(key)
        if existing is not None:
            return existing

        # Compile based on whether this is a synthetic or defined symbol
        if isinstance(self, SyntheticSymbol):
            nested_definition = None
        elif isinstance(self, DefinedSymbol):
            definition = self.definition
            if isinstance(definition, _ScopeDefinition):
                nested_definition = definition.get(key)
            else:
                # Leaf symbol - no nested items
                raise KeyError(key)
        else:
            # Unknown symbol type - no nested items
            raise KeyError(key)
        if nested_definition is not None:
            compiled_symbol = nested_definition.compile(self, cast(str, key))
        else:

            compiled_symbol = SyntheticSymbol(
                key=key,
                outer=self,
            )
            if not compiled_symbol.strict_super_indices:
                raise KeyError(key)

        self.intern_pool[key] = cast("Symbol", compiled_symbol)
        return compiled_symbol

    @cached_property
    def instance(self) -> "Symbol | InstanceSymbolSentinel":
        """Get or create the instance symbol for this symbol.

        Returns InstanceSymbolSentinel.ALREADY_INSTANCE if this is already an instance symbol.
        """
        match self.prototype:
            case PrototypeSymbolSentinel.NOT_INSTANCE:
                return replace(self, prototype=self)
            case Symbol():
                return InstanceSymbolSentinel.ALREADY_INSTANCE

    @property
    def depth(self) -> int:
        """Return the depth of this symbol in the scope hierarchy.

        Root symbols (outer=OuterSentinel.ROOT) have depth 0.
        Nested symbols have depth = outer.depth + 1.
        """
        match self.outer:
            case OuterSentinel.ROOT:
                return 0
            case Symbol() as outer_symbol:
                return outer_symbol.depth + 1

    @cached_property
    def getter(self) -> Callable[[CapturedScopes], "Node"]:
        """Create getter function for accessing this resource.

        Raises:
            ValueError: If called on a root symbol (key=KeySentinel.ROOT).
        """
        match self.key:
            case KeySentinel.ROOT:
                raise ValueError("Root symbols do not have a getter")
            case str() as string_key:
                index = self.depth - 1
                return _make_jit_getter(string_key, index)
            case _ as hashable_key:
                index = self.depth - 1
                return lambda captured_scopes: captured_scopes[index][hashable_key]

    @cached_property
    def elected_merger_index(self) -> SymbolIndexSentinel | int:
        """
        Elect the merger from self and base symbols.

        Implements the merger election algorithm at compile time:
        1. If exactly one pure Merger exists, it is elected
        2. If multiple pure Mergers exist, raises ValueError
        3. If no pure Mergers exist, raises NotImplementedError

        Returns:
            SymbolIndexSentinel.OWN if self is the elected merger,
            or the index in base_indices if a base symbol is elected.
        """
        self_is_pure_merger = isinstance(self, MergerSymbol)

        pure_merger_indices: list[int] = [
            index
            for index, base_symbol in enumerate(self.generate_strict_super())
            if isinstance(base_symbol, MergerSymbol)
        ]

        total_pure_mergers = len(pure_merger_indices) + (
            1 if self_is_pure_merger else 0
        )

        if total_pure_mergers == 1:
            if self_is_pure_merger:
                return SymbolIndexSentinel.OWN
            (single_index,) = pure_merger_indices
            return single_index
        elif total_pure_mergers > 1:
            raise ValueError("Multiple Factory definitions provided")
        else:
            raise NotImplementedError("No Factory definition provided")

    @final
    def generate_strict_super(self):
        """
        Generate the strict super symbols (all direct and transitive bases, excluding self).

        .. todo::

            This method will be used with the new ``Scope.captured_scopes_sequence``
            (which replaces ``Scope.mixins``) via
            ``zip(mixin.generate_strict_super(), scope.captured_scopes_sequence)``.
        """
        return iter(self.strict_super_indices.keys())

    @final
    @cached_property
    def union_indices(self) -> Mapping["Symbol", int]:
        """Collect base_indices from outer's strict super symbols."""
        match (self.outer, self.key):
            case (Symbol() as outer_scope, key) if not isinstance(key, KeySentinel):
                return _collect_union_indices(outer_scope, key)
            case _:
                return {}

    @final
    @cached_property
    def direct_base_indices(
        self,
    ) -> dict["Symbol", NestedSymbolIndex]:
        match (self, self.outer):
            case (DefinedSymbol(definition=definition), Symbol() as outer_scope):
                return {
                    _resolve_symbol_reference(
                        reference, outer_scope, Symbol
                    ): NestedSymbolIndex(
                        primary_index=OwnBaseIndex(index=own_base_index),
                        secondary_index=SymbolIndexSentinel.OWN,
                    )
                    for own_base_index, reference in enumerate(definition.bases)
                }
            case _:
                return {}

    @final
    @cached_property
    def transitive_base_indices(
        self,
    ) -> dict["Symbol", NestedSymbolIndex]:
        match (self, self.outer):
            case (DefinedSymbol(definition=definition), Symbol() as outer_scope):
                result: dict["Symbol", NestedSymbolIndex] = {}
                return {
                    linearized_base: (
                        NestedSymbolIndex(
                            primary_index=OwnBaseIndex(index=own_base_index),
                            secondary_index=linearized_index,
                        )
                    )
                    for own_base_index, reference in enumerate(definition.bases)
                    # Linearized strict super symbols of the extend reference
                    for linearized_index, linearized_base in enumerate(
                        _resolve_symbol_reference(
                            reference, outer_scope, SemigroupSymbol
                        ).generate_strict_super()
                    )
                    if (linearized_base not in result)
                }
            case _:
                return {}

    @final
    @cached_property
    def linearized_base_indices(
        self,
    ):
        """
        Linearized indices for own bases (extend references) and their strict super symbols.

        This includes:
        1. Direct extend references from ``self.definition.bases``
        2. Strict super mixins from each extend reference's ``generate_strict_super()``

        Uses ``OwnBaseIndex`` to distinguish from outer base indices.
        """
        return ChainMap(
            self.direct_base_indices,
            self.transitive_base_indices,
        )

    @final
    @property
    def strict_super_indices(
        self,
    ):
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

        .. todo::

            Exclude ``_SyntheticSymbol`` from this mapping. Synthetic mixins are placeholders
            for leaf resources that have no definition in the current scope (only inherited
            from base classes). They should not appear in the linearized base indices because
            they don't contribute any actual behavior.
        """

        return ChainMap(
            self.linearized_base_indices,
            self.linearized_union_indices,
        )

    @cached_property
    def linearized_union_indices(
        self,
    ):
        """
        Index mapping for outer base classes (common to both subclasses).

        This includes:
        1. Outer base classes from ``self.base_indices``
        2. Strict super mixins from each outer base class's ``generate_strict_super()``

        Uses ``ChainMap`` to avoid dictionary unpacking. Outer base classes take
        precedence over their strict super symbols (first map in ChainMap wins on key collision).
        """
        union_own_indices = {
            base: NestedSymbolIndex(
                primary_index=OuterBaseIndex(index=primary_index),
                secondary_index=SymbolIndexSentinel.OWN,
            )
            for base, primary_index in self.union_indices.items()
        }
        linearized_union_base_indices = {
            linearized_base: NestedSymbolIndex(
                primary_index=OuterBaseIndex(index=primary_index),
                secondary_index=secondary_index,
            )
            for base, primary_index in self.union_indices.items()
            for secondary_index, linearized_base in enumerate(
                base.generate_strict_super()
            )
        }
        return ChainMap(union_own_indices, linearized_union_base_indices)


@dataclass(kw_only=True, frozen=True, eq=False)
class DefinedSymbol(Symbol):
    """
    Marker base class for defined symbols (has local definition in current scope).

    Defined symbols are created when a resource or nested scope has a local definition
    in the current scope. They have access to the full definition information.

    Subclasses
    ==========

    - ``_NestedMergerSymbol``, ``_EndofunctionSymbol``, etc.: For leaf resources
    - ``DefinedScopeSymbol``: For nested scopes
    - ``RootScopeSymbol``: For root symbol

    All subclasses have ``definition: Definition`` (narrowed from the base class type).
    """

    definition: Final["Definition"]


class Mixin(ABC):
    """Base class for Merger, Patcher, and SyntheticResourceMixin."""


class SymbolIndexSentinel(Enum):
    """Sentinel value for symbol indices indicating the symbol itself (not a base)."""

    OWN = auto()


class OuterSentinel(Enum):
    """Sentinel value for symbols that have no outer scope (root symbols)."""

    ROOT = auto()


class KeySentinel(Enum):
    """Sentinel value for symbols that have no key (root symbols)."""

    ROOT = auto()


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
    Two-dimensional index of Symbol in outer ScopeSymbol, supporting O(1) random access.

    Basic Concept
    =============

    ``NestedSymbolIndex`` uses a two-dimensional index ``(primary_index, secondary_index)`` to locate
    a Symbol's position in its outer ScopeSymbol's linearized inheritance chain.

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

    Given ``nested_symbol: NestedScopeSymbol`` with ``key`` in ``outer: Symbol``,
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
        target = _resolve_symbol_reference(extend_refs[i], outer, NestedScopeSymbol)

    - ``NestedSymbolIndex(primary_index=OwnBaseIndex(index=i), secondary_index=j)``::

        # The j-th strict super symbol of extend_refs[i]
        extend_refs = nested_symbol.definition.bases
        own_base = _resolve_symbol_reference(extend_refs[i], outer, NestedScopeSymbol)
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
        mapping_base_indices: Mapping[NestedScopeSymbol, NestedSymbolIndex]

    JIT Usage Example::

        # Directly access all Mergers without traversal and isinstance checks
        for merger, index in scope.symbol.merger_base_indices.items():
            mixin_result = merger(captured_scopes)  # Return type guaranteed to be Merger
    """

    primary_index: Final[PrimarySymbolIndex]
    secondary_index: Final[SecondarySymbolIndex]


@dataclass(kw_only=True, frozen=True, eq=False)
class MergerSymbol(
    Symbol["Merger[TPatch_contra, TResult_co]"],
    Generic[TPatch_contra, TResult_co],
):
    """
    Intermediate base class for Symbol subclasses that return Merger.

    Use ``isinstance(symbol, MergerSymbol)`` to check if a symbol returns a Merger.

    Type Parameters
    ===============

    - ``TPatch_contra``: The type of patches this Merger accepts (contravariant)
    - ``TResult_co``: The type of result this Merger produces (covariant)
    """

    @abstractmethod
    def bind(
        self, captured_scopes: CapturedScopes, /
    ) -> "Merger[TPatch_contra, TResult_co]":
        """Retrieve the Merger for the given captured scopes."""


@dataclass(kw_only=True, frozen=True, eq=False)
class PatcherSymbol(Symbol["Patcher[TPatch_co]"], Generic[TPatch_co]):
    """
    Intermediate base class for Symbol subclasses that return Patcher.

    Use ``isinstance(symbol, PatcherSymbol)`` to check if a symbol returns a Patcher.

    Type Parameters
    ===============

    - ``TPatch_co``: The type of patches this Patcher produces (covariant)
    """

    @abstractmethod
    def bind(self, captured_scopes: CapturedScopes, /) -> "Patcher[TPatch_co]":
        """Retrieve the Patcher for the given captured scopes."""


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class SyntheticSymbol(Symbol["Synthetic"]):
    """
    Symbol for inherited-only resources (no local definition).

    Synthetic symbols are created when a resource or nested scope is inherited from
    base classes but has no local definition in the current scope.

    SyntheticSymbol produces a ``Synthetic`` mixin that is excluded from merger
    election. The actual Merger comes from base classes.
    """

    def bind(self, captured_scopes: CapturedScopes, /) -> "Synthetic":
        """Return a Synthetic mixin."""
        return Synthetic(symbol=self, captured_scopes=captured_scopes)


TResult = TypeVar("TResult")


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class FunctionalMergerSymbol(
    DefinedSymbol,
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
            "FunctionalMergerDefinition[TPatch_contra, TResult_co]", self.definition
        )
        assert isinstance(
            self.key, str
        ), f"Merger key must be a string, got {type(self.key)}"
        match self.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have JIT-compiled functions")
            case Symbol() as outer_scope:
                return _resolve_dependencies_jit_using_symbol(
                    outer_scope,
                    definition.function,
                    self.key,
                )

    @override
    def bind(
        self, captured_scopes: CapturedScopes, /
    ) -> "FunctionalMerger[TPatch_contra, TResult_co]":
        return FunctionalMerger(symbol=self, captured_scopes=captured_scopes)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class EndofunctionMergerSymbol(
    DefinedSymbol,
    MergerSymbol["Endofunction[TResult]", TResult],
    Generic[TResult],
):
    """Symbol for _EndofunctionDefinition.

    Returns ``Merger[Endofunction[T], T]`` which accepts endofunction patches.
    """

    @cached_property
    def jit_compiled_function(self) -> Callable[[CapturedScopes], TResult]:
        """JIT-compiled function using mixin-based dependency resolution."""
        definition = cast("EndofunctionMergerDefinition[TResult]", self.definition)
        assert isinstance(
            self.key, str
        ), f"Resource key must be a string, got {type(self.key)}"
        match self.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have JIT-compiled functions")
            case Symbol() as outer_scope:
                return _resolve_dependencies_jit_using_symbol(
                    outer_scope,
                    definition.function,
                    self.key,
                )

    @override
    def bind(self, captured_scopes: CapturedScopes, /) -> "EndofunctionMerger[TResult]":
        return EndofunctionMerger(symbol=self, captured_scopes=captured_scopes)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class SinglePatcherSymbol(DefinedSymbol, PatcherSymbol[TPatch_co], Generic[TPatch_co]):
    """NestedSymbol for _SinglePatchDefinition."""

    @cached_property
    def jit_compiled_function(self) -> Callable[[CapturedScopes], TPatch_co]:
        """JIT-compiled function using mixin-based dependency resolution."""
        definition = cast("SinglePatcherDefinition[TPatch_co]", self.definition)
        assert isinstance(
            self.key, str
        ), f"Patch key must be a string, got {type(self.key)}"
        match self.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have JIT-compiled functions")
            case Symbol() as outer_scope:
                return _resolve_dependencies_jit_using_symbol(
                    outer_scope,
                    definition.function,
                    self.key,
                )

    @override
    def bind(self, captured_scopes: CapturedScopes, /) -> "SinglePatcher[TPatch_co]":
        return SinglePatcher(symbol=self, captured_scopes=captured_scopes)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class MultiplePatcherSymbol(
    DefinedSymbol, PatcherSymbol[TPatch_co], Generic[TPatch_co]
):
    """NestedSymbol for _MultiplePatchDefinition."""

    @cached_property
    def jit_compiled_function(self) -> Callable[[CapturedScopes], Iterable[TPatch_co]]:
        """JIT-compiled function using mixin-based dependency resolution."""
        definition = cast("MultiplePatcherDefinition[TPatch_co]", self.definition)
        assert isinstance(
            self.key, str
        ), f"Patch key must be a string, got {type(self.key)}"
        match self.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have JIT-compiled functions")
            case Symbol() as outer_scope:
                return _resolve_dependencies_jit_using_symbol(
                    outer_scope,
                    definition.function,
                    self.key,
                )

    @override
    def bind(self, captured_scopes: CapturedScopes, /) -> "MultiplePatcher[TPatch_co]":
        return MultiplePatcher(symbol=self, captured_scopes=captured_scopes)


class SemigroupSymbol(MergerSymbol["StaticScope", "StaticScope"]):
    """
    Marker base class for Symbols that return a Semigroup (both Merger and Patcher).

    Inherits from ``MergerSymbol`` so that ``isinstance(symbol, MergerSymbol)``
    returns True, which is needed for ``elected_merger_index`` to recognize
    scope symbols as valid merger candidates.

    Use ``isinstance(mixin, SemigroupSymbol)`` to check if a mixin returns
    an evaluator that is both Merger and Patcher (e.g., ``ScopeSemigroup``).

    Subclass: ``DefinedScopeSymbol``.
    """


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class DefinedScopeSymbol(DefinedSymbol, SemigroupSymbol):
    """
    Scope symbol for defined scopes (has local definition with extend references).

    Defined mixins are created when a nested scope has a local definition in the current
    scope. They use the scope class from the definition and include extend references.
    """

    definition: "_ScopeDefinition"  # type: ignore[assignment]  # Narrowing from base class

    @override
    def bind(self, captured_scopes: CapturedScopes, /) -> "ScopeSemigroup":
        """Resolve resources including extend references from definition."""
        match self.outer:
            case OuterSentinel.ROOT:
                raise NotImplementedError("TODO: support bind with root!")
            case Symbol() as outer_scope:
                pass
        assert not isinstance(self.key, KeySentinel)

        def scope_factory() -> StaticScope:
            assert (
                captured_scopes
            ), "captured_scopes must not be empty when resolving resources"

            def generate_all_symbol_items() -> Iterator[tuple[Symbol, CapturedScopes]]:
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

            return StaticScope(
                symbols=dict(generate_all_symbol_items()),
                symbol=self,
            )

        return ScopeSemigroup(
            scope_factory=scope_factory,
            access_path_outer=outer_scope,
            key=self.key,
        )


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
        Provide ResourceConfig configuration through new decorators to support 26 combinations
        of behaviors on demand. Note that this configuration is static, independent of Scope
        instances, and may be compiled into bytecode by Symbol in the future.
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

            @scope
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
    ) -> Mapping[Symbol, CapturedScopes]:
        """The symbols that provide resources for this scope, keyed by symbol.

        Each scope's own properties (not from extend=) are stored at
        symbols[self.symbol]. Extended scopes contribute their symbols
        with their original symbol keys.

        .. todo:: Replace ``dict`` with ``ChainMap``.
        """
        ...

    symbol: Symbol
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
            if isinstance(current_symbol, SyntheticSymbol):
                # Synthetic symbols don't have their own keys
                continue
            assert isinstance(current_symbol, DefinedSymbol)
            assert isinstance(current_symbol.definition, _ScopeDefinition)
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
class StaticScope(Scope):
    """
    A static scope representing class/module level definitions.

    StaticScope stores symbols directly, caches resource lookups,
    and supports ``__call__`` to create InstanceScope with additional kwargs.
    """

    symbols: Mapping[Symbol, CapturedScopes]  # type: ignore[misc]
    """
    .. todo::

        Delete this field and replace with ``captured_scopes_sequence: Sequence[CapturedScopes]``
        that is isomorphic to ``symbol.generate_strict_super()``.

        This enables:

        - Zip with ``generate_strict_super()`` to pair each Symbol with its CapturedScopes
        - O(1) random access outer scope using ``NestedSymbolIndex`` to construct
          ``Sequence[CapturedScopes]``
    """

    symbol: Symbol  # type: ignore[misc]

    _cache: MutableMapping[Hashable, "Node"] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @override
    def __getitem__(self, key: Hashable) -> "Node":
        """
        .. note:: This method uses the two-arg super() as a workaround for https://github.com/python/cpython/pull/124455
        """
        if key not in self._cache:
            value = super(StaticScope, self).__getitem__(key)
            self._cache[key] = value
            return value
        else:
            return self._cache[key]

    def __call__(self, **kwargs: object) -> "InstanceScope":
        """
        Create an InstanceScope with the given kwargs.
        """
        instance_symbol = self.symbol.instance
        assert isinstance(
            instance_symbol, Symbol
        ), "StaticScope.symbol should not already be an instance symbol"
        return InstanceScope(
            base_scope=self,
            kwargs=kwargs,
            symbol=instance_symbol,
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
    symbol: Symbol  # type: ignore[misc]

    @property
    @override
    def symbols(
        self,
    ) -> Mapping[Symbol, CapturedScopes]:
        return self.base_scope.symbols

    @override
    def __getitem__(self, key: Hashable) -> Node:
        if isinstance(key, str) and key in self.kwargs:
            value = self.kwargs[key]

            def generate_resource() -> Iterator[Mixin]:
                # Yield the kwargs value as a Merger
                yield KeywordArgumentMerger(base_value=cast(Resource, value))
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


class Merger(Mixin, Generic[TPatch_contra, TResult_co]):
    @abstractmethod
    def merge(self, patches: Iterator[TPatch_contra]) -> TResult_co: ...


class Patcher(Mixin, Iterable[TPatch_co], Generic[TPatch_co]):
    """
    An Patcher provides extra data to be applied to a Node created by a ``Merger``.
    """


TScope = TypeVar("TScope", bound=StaticScope)


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class KeywordArgumentMerger(
    Generic[TResult], Merger[Callable[[TResult], TResult], TResult]
):
    """Merger that applies patches as endofunctions via reduce."""

    base_value: TResult

    @override
    def merge(self, patches: Iterator[Callable[[TResult], TResult]]) -> TResult:
        return reduce(lambda acc, endo: endo(acc), patches, self.base_value)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class FunctionalMerger(Merger[TPatch_contra, TResult_co]):
    """Mixin for _NestedMergerSymbol."""

    symbol: Final["FunctionalMergerSymbol[TPatch_contra, TResult_co]"]
    captured_scopes: Final[CapturedScopes]

    @override
    def merge(self, patches: Iterator[TPatch_contra]) -> TResult_co:
        aggregation_function = self.symbol.jit_compiled_function(self.captured_scopes)
        return aggregation_function(patches)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class EndofunctionMerger(Merger["Endofunction[TResult]", TResult]):
    """Mixin for _EndofunctionSymbol."""

    symbol: Final["EndofunctionMergerSymbol[TResult]"]
    captured_scopes: Final[CapturedScopes]

    @override
    def merge(self, patches: Iterator["Endofunction[TResult]"]) -> TResult:
        base_value = self.symbol.jit_compiled_function(self.captured_scopes)
        return reduce(
            lambda accumulator, endofunction: endofunction(accumulator),
            patches,
            base_value,
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class SinglePatcher(Patcher[TPatch_co]):
    """Mixin for _SinglePatchSymbol."""

    symbol: Final["SinglePatcherSymbol[TPatch_co]"]
    captured_scopes: Final[CapturedScopes]

    @override
    def __iter__(self) -> Iterator[TPatch_co]:
        yield self.symbol.jit_compiled_function(self.captured_scopes)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class MultiplePatcher(Patcher[TPatch_co]):
    """Mixin for _NestedMultiplePatchSymbol."""

    symbol: Final["MultiplePatcherSymbol[TPatch_co]"]
    captured_scopes: Final[CapturedScopes]

    @override
    def __iter__(self) -> Iterator[TPatch_co]:
        yield from self.symbol.jit_compiled_function(self.captured_scopes)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class Synthetic(Mixin):
    """
    Mixin for SyntheticSymbol.

    This is NOT a Patcher or Merger. It is excluded from merger election
    because it doesn't satisfy ``isinstance(item, Merger)`` or
    ``isinstance(item, Patcher)`` in ``_evaluate_resource``.
    """

    symbol: Final["SyntheticSymbol"]
    captured_scopes: Final[CapturedScopes]


def _symbol_getitem(
    symbol_mapping: Symbol,
    captured_scopes: CapturedScopes,
    key: Hashable,
    /,
) -> Callable[[Scope], Mixin]:
    """
    Get a factory function from a dependency graph by key.

    Uses ``symbol_mapping[key]`` to get the NestedSymbol (which IS-A Symbol),
    then creates a closure that calls ``bind`` with the captured scopes.
    """
    nested_symbol = symbol_mapping[key]

    def bind_scope(scope: Scope) -> Mixin:
        inner_captured_scopes: CapturedScopes = (*captured_scopes, scope)
        mixin_result = cast(Symbol[Mixin], nested_symbol).bind(inner_captured_scopes)
        # If mixin_result is a ScopeSemigroup, set access_path_outer to the scope's symbol
        if isinstance(mixin_result, ScopeSemigroup):
            return replace(mixin_result, access_path_outer=scope.symbol)
        return mixin_result

    return bind_scope


def _collect_union_indices(
    outer_symbol: "Symbol", key: Hashable, /
) -> Mapping["Symbol", int]:
    """Collect base_indices from outer_symbol's strict super symbols."""
    return {
        cast("Symbol", item_symbol): index
        for index, base in enumerate(
            cast(Iterator["Symbol"], outer_symbol.generate_strict_super())
        )
        if (item_symbol := base.get(key)) is not None
    }


def _evaluate_resource(
    resource_generator: Callable[[], Iterator[Mixin]],
) -> Node:
    """
    Evaluate a resource by selecting a Merger and applying Patches.

    Algorithm for selecting the Merger:
    0. SyntheticResourceMixin items are excluded from election (they are placeholders
       for inherited-only resources and contribute no actual patches).
    1. If there is exactly one item that is a Merger but NOT a Patch (pure Merger),
       it is selected as the Merger. All other items (including those that are both)
       are treated as Patches.
    2. If there are multiple pure Mergers, a ValueError is raised.
    3. If there are no pure Mergers, but there are items that are both Merger and Patch:
       One is arbitrarily selected as the Merger, and the rest are treated as Patches.
       (This assumes the semantics of these items satisfy commutativity).
    4. If there are no Mergers (pure or dual), a NotImplementedError is raised.
    """
    items = tuple(
        item for item in resource_generator() if not isinstance(item, Synthetic)
    )
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

    return selected_merger.merge(flat_patches)


@dataclass(kw_only=True, frozen=True, eq=False)
class Definition(ABC):
    bases: tuple["ResourceReference[Hashable]", ...] = ()

    @abstractmethod
    def compile(self, outer: Symbol, key: str, /) -> Symbol:
        """
        Compile this definition into a Symbol for the given outer ScopeSymbol.

        :param outer: The parent ScopeSymbol that will contain this Symbol.
        :param key: The key/name for this resource in the parent mapping.
        :return: A Symbol instance ready for evaluation.
        """
        raise NotImplementedError()


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class MergerDefinition(Definition, Generic[TPatch_contra, TResult_co]):
    is_eager: bool = False
    is_local: bool = False

    @abstractmethod
    def compile(self, outer: Symbol, key: str, /) -> Symbol:
        raise NotImplementedError()


class PatcherDefinition(Definition, Generic[TPatch_co]):
    @abstractmethod
    def compile(self, outer: Symbol, key: str, /) -> Symbol:
        raise NotImplementedError()


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FunctionalMergerDefinition(MergerDefinition[TPatch_contra, TResult_co]):
    """Definition for merge decorator."""

    function: Callable[..., Callable[[Iterator[TPatch_contra]], TResult_co]]

    def compile(
        self, outer: Symbol, key: str, /
    ) -> "FunctionalMergerSymbol[TPatch_contra, TResult_co]":
        return FunctionalMergerSymbol(
            key=key,
            outer=outer,
            definition=self,
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class EndofunctionMergerDefinition(
    Generic[TResult], MergerDefinition[Callable[[TResult], TResult], TResult]
):
    """Definition for resource decorator."""

    function: Callable[..., TResult]

    def compile(
        self, outer: Symbol, key: str, /
    ) -> "EndofunctionMergerSymbol[TResult]":
        return EndofunctionMergerSymbol(
            key=key,
            outer=outer,
            definition=self,
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class SinglePatcherDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patch decorator (single patch)."""

    function: Callable[..., TPatch_co]

    def compile(self, outer: Symbol, key: str, /) -> "SinglePatcherSymbol[TPatch_co]":
        return SinglePatcherSymbol(
            key=key,
            outer=outer,
            definition=self,
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class MultiplePatcherDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patches decorator (multiple patches)."""

    function: Callable[..., Iterable[TPatch_co]]

    def compile(self, outer: Symbol, key: str, /) -> "MultiplePatcherSymbol[TPatch_co]":
        return MultiplePatcherSymbol(
            key=key,
            outer=outer,
            definition=self,
        )


class Semigroup(Merger[T, T], Patcher[T], Generic[T]):
    pass


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class ScopeSemigroup(Semigroup[StaticScope]):
    """
    Semigroup for merging Scope instances from extended scopes.

    .. todo:: Change to only support merging ``StaticScope``, prohibit merging ``InstanceScope``.

        The type signature should be changed to ``Merger[StaticScope, StaticScope]``, and add
        assertions in the ``create`` method to ensure ``InstanceScope`` is not passed in.
    """

    scope_factory: Final[Callable[[], StaticScope]]
    access_path_outer: Final[Symbol]
    key: Final[Hashable]

    @override
    def merge(self, patches: Iterator[StaticScope]) -> StaticScope:
        """
        Create a merged Scope from factory and patches.

        .. todo:: Phase 9: Replace ``generate_all_symbol_items`` with ``ChainMap``.
        """

        def all_scopes() -> Iterator[StaticScope]:
            yield from self
            return (yield from patches)

        scopes_tuple = tuple(all_scopes())
        winner_class = _calculate_most_derived_class(*(type(p) for p in scopes_tuple))

        def generate_all_symbol_items() -> Iterator[tuple[Symbol, CapturedScopes]]:
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
            symbol=self.access_path_outer[self.key],
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
    starting_symbol: "Symbol",
    expected_type: type[TSymbol],
) -> TSymbol:
    """
    Resolve a ResourceReference to a Symbol using the given symbol as starting point.

    This is the compile-time analog of :func:`_resolve_resource_reference`. Instead of
    traversing Scope objects at runtime, it traverses ScopeSymbol objects at compile-time.

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
            current: Symbol = starting_symbol
            for level in range(levels_up):
                match current.outer:
                    case OuterSentinel.ROOT:
                        raise ValueError(
                            f"Cannot navigate up {levels_up} levels: "
                            f"reached root at level {level}"
                        )
                    case Symbol() as outer_scope:
                        current = outer_scope
        case AbsoluteReference(path=parts):
            # Navigate to root
            current = starting_symbol
            while True:
                match current.outer:
                    case OuterSentinel.ROOT:
                        break
                    case Symbol() as outer_scope:
                        current = outer_scope
        case _ as unreachable:
            assert_never(unreachable)

    # Navigate through parts
    for part_index, part in enumerate(parts):
        resolved = current[part]
        if not isinstance(resolved, Symbol):
            path_so_far = ".".join(str(p) for p in parts[: part_index + 1])
            raise TypeError(
                f"Expected ScopeSymbol while resolving reference, "
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
                 traverses ScopeSymbol objects instead of Scope objects.
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
class _ScopeDefinition(
    Mapping[Hashable, Definition],
    Definition,
):
    """Base class for scope definitions that create Scope instances from underlying objects."""

    underlying: object

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

    def compile(self, outer: Symbol, key: str, /) -> "DefinedScopeSymbol":
        """
        Compile this definition mapping into a DefinedScopeSymbol.

        :param outer: The parent ScopeSymbol that will contain this Symbol.
        :param key: The key/name for this scope in the parent mapping.
        :return: A DefinedScopeSymbol instance ready for evaluation.
        """
        nested_symbol_mapping = DefinedScopeSymbol(
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
class _PackageScopeDefinition(_ScopeDefinition):
    """A definition for packages that discovers submodules via pkgutil."""

    underlying: ModuleType

    def __iter__(self) -> Iterator[Hashable]:
        yield from super(_PackageScopeDefinition, self)

        for mod_info in pkgutil.iter_modules(self.underlying.__path__):
            yield mod_info.name

    @override
    def __getitem__(self, key: Hashable) -> Definition:
        """Get a Definition by key name, including lazily imported submodules."""
        try:
            return super(_PackageScopeDefinition, self).__getitem__(key)
        except KeyError:
            pass

        full_name = f"{self.underlying.__name__}.{key}"
        try:
            spec = importlib.util.find_spec(full_name)
        except ImportError as error:
            raise KeyError(key) from error

        if spec is None:
            raise KeyError(key)

        submod = importlib.import_module(full_name)

        if hasattr(submod, "__path__"):
            return _PackageScopeDefinition(underlying=submod)
        else:
            return _ScopeDefinition(underlying=submod)


def scope(c: object) -> _ScopeDefinition:
    """
    Decorator that converts a class into a ScopeDefinition.
    Nested classes MUST be decorated with @scope to be included as sub-scopes.

    Example - Using @extend to inherit from another scope::

        @extend(RelativeReference(levels_up=1, path=("Base",)))
        @scope
        class MyScope:
            @patch
            def foo() -> Callable[[int], int]:
                return lambda x: x + 1

    Example - Union mounting multiple scopes across modules::

        Multiple ``@scope`` definitions with the same name are automatically merged
        as semigroups. This is the recommended way to create union mount points::

            # In branch0.py:
            @scope
            class union_mount_point:
                pass  # Base empty scope

            # In branch1.py:
            @scope
            class union_mount_point:
                @resource
                def foo() -> str:
                    return "foo"

            # In branch2.py:
            @scope
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
    return _ScopeDefinition(underlying=c)


TDefinition = TypeVar("TDefinition", bound=Definition)


def extend(
    *bases: "ResourceReference[Hashable]",
) -> Callable[[TDefinition], TDefinition]:
    """
    Decorator that adds base references to a Definition.

    Use this decorator to specify that a scope extends other scopes,
    inheriting their mixins.

    :param bases: ResourceReferences to other scopes whose mixins should be included.
                  This allows composing scopes without explicit merge operations.

    Example::

        @extend(RelativeReference(levels_up=1, path=("Base",)))
        @scope
        class MyScope:
            @patch
            def foo() -> Callable[[int], int]:
                return lambda x: x + 1

    """

    def decorator(definition: TDefinition) -> TDefinition:
        return replace(definition, bases=bases)

    return decorator


def _parse_package(module: ModuleType) -> _ScopeDefinition:
    """
    Parses a module into a NamespaceDefinition.

    Only module-level attributes explicitly decorated with @resource, @patch, @patch_many, or @merge are included.
    Nested modules and packages are recursively parsed with lazy loading.

    IMPORTANT: Bare callables (without decorators) are NOT automatically included.
    Users must explicitly mark all injectable definitions with appropriate decorators.

    For packages (modules with __path__), uses pkgutil.iter_modules to discover submodules
    and importlib.import_module to lazily import them when accessed.
    """
    if hasattr(module, "__path__"):
        return _PackageScopeDefinition(underlying=module)
    return _ScopeDefinition(underlying=module)


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

    Note: For union mounting multiple scopes, use ``@scope`` semigroups instead.
    See :func:`scope` for examples.
    """
    return FunctionalMergerDefinition(function=callable)


def patch(
    callable: Callable[..., TPatch_co],
) -> PatcherDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return SinglePatcherDefinition(function=callable)


def patch_many(
    callable: Callable[..., Iterable[TPatch_co]],
) -> PatcherDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return MultiplePatcherDefinition(function=callable)


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

    return MultiplePatcherDefinition(function=empty_patches_provider)


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
    return EndofunctionMergerDefinition(function=callable)


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
    namespace: ModuleType | _ScopeDefinition,
) -> StaticScope:
    """
    Resolves a Scope from the given object using the provided lexical scope.

    :param namespace: Module or namespace definition (decorated with @scope) to resolve resources from.
    :return: An instance of the cls type with resolved mixins.

    Example::

        root = mount(MyNamespace)

    """
    captured_scopes: CapturedScopes = ()

    namespace_definition: _ScopeDefinition
    if isinstance(namespace, _ScopeDefinition):
        namespace_definition = namespace
    elif isinstance(namespace, ModuleType):
        namespace_definition = _parse_package(namespace)
    else:
        assert_never(namespace)

    root_symbol = DefinedScopeSymbol(
        definition=namespace_definition,
        outer=OuterSentinel.ROOT,
        key=KeySentinel.ROOT,
    )
    return StaticScope(
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


def _find_param_in_symbol_chain(param_name: str, starting_symbol: Symbol) -> "Symbol":
    """
    Find a parameter in the symbol chain (lexical scope + extends).

    Traverses up the outer chain to find the parameter. Each symbol's __getitem__
    handles extends resolution, so we only need to traverse the lexical scope chain.

    :param param_name: The name of the parameter to find.
    :param starting_symbol: The starting ScopeSymbol to search from.
    :return: The Symbol (leaf or scope).
    :raises KeyError: If the parameter is not found in the symbol chain.
    """
    current: Symbol = starting_symbol
    while True:
        if param_name in current:
            param_symbol = current[param_name]
            return param_symbol
        match current.outer:
            case OuterSentinel.ROOT:
                raise KeyError(f"Parameter '{param_name}' not found in symbol chain")
            case Symbol() as outer_scope:
                current = outer_scope


def _is_param_in_symbol_chain(param_name: str, starting_symbol: Symbol) -> bool:
    """Check if a parameter is resolvable from the symbol chain."""
    current: Symbol = starting_symbol
    while True:
        if param_name in current:
            return True
        match current.outer:
            case OuterSentinel.ROOT:
                return False
            case Symbol() as outer_scope:
                current = outer_scope


def _resolve_dependencies_jit_using_symbol(
    outer_symbol: Symbol,
    function: Callable[P, T],
    name: str,
) -> Callable[[CapturedScopes], T]:
    """
    Resolve dependencies using the mixin chain.

    For each parameter p:
    1. param_symbol = _find_param_in_symbol_chain(p.name, outer_symbol)
    2. Use param_symbol.getter for JIT code generation

    This handles both extends (via ScopeSymbol.__getitem__) and lexical scope
    (via traversing the outer chain).

    Special case: when param_name == name, starts search from outer_symbol.outer to
    avoid self-dependency, mimicking pytest fixture behavior.

    :param outer_symbol: The ScopeSymbol containing the resource being resolved.
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
            match outer_symbol.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Same-name dependency '{name}' at root level is not allowed"
                    )
                case Symbol() as outer_scope:
                    param_symbol = _find_param_in_symbol_chain(
                        parameter.name, outer_scope
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

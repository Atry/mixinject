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

    from mixinject import resource, patch, evaluate

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

    root = evaluate(...)
    root.greeting  # "Hello!"
    root.ignored_function  # AttributeError: 'StaticScope' object has no attribute 'ignored_function'

Union Filesystem Analogy
========================

If we make an analogy to union filesystems:

- :class:`Scope` objects are like directory objects
- Resources are like files
- Modules, packages, callables, and :class:`ScopeDefinition` are filesystem definitions before evaluation
- The compiled result (from :func:`evaluate`) is a concrete :class:`Scope` that implements resource access

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

    root = evaluate(Outer)
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

At the framework entry point (:func:`evaluate`), users can pass a package, module,
or object, which is evaluated into a root :class:`Scope`, similar to
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
    from mixinject import evaluate

    root = evaluate(config)(settings={"host": "db.example.com", "port": "3306"})
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

    # Create a Scope and inject values using evaluate
    @scope
    class Config:
        @extern
        def setting(): ...
        @extern
        def count(): ...

    scope = evaluate(Config)
    new_scope = scope(setting="value", count=42)

    # Access injected values
    assert new_scope.setting == "value"
    assert new_scope.count == 42

Primary Use Case
----------------

The primary use of Scope as Callable is to provide base values for parameter injection.
By using :meth:`Scope.__call__` in an outer scope to inject parameter values, resources in
modules can access these values via symbol table lookup::

    # Provide base value in outer scope via evaluate
    @scope
    class Config:
        @extern
        def db_config(): ...

    outer_scope = evaluate(Config)(db_config={"host": "localhost", "port": "5432"})

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
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import cached_property, reduce
import importlib
import importlib.util
from inspect import Parameter, signature
from itertools import chain
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
    Self,
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


class RelativeReferenceSentinel(Enum):
    """Sentinel value for RelativeReference lookup failures."""

    NOT_FOUND = auto()


class PrototypeSymbolSentinel(Enum):
    """Sentinel value for symbols that are not instance symbols."""

    NOT_INSTANCE = auto()


class InstanceSymbolSentinel(Enum):
    """Sentinel value for instance_symbol when called on an already-instance symbol."""

    ALREADY_INSTANCE = auto()


TMixin_co = TypeVar("TMixin_co", bound="Mixin", covariant=True)


@dataclass(kw_only=True, frozen=True, eq=False)
class Symbol(
    Mapping[Hashable, "Symbol"],
    ABC,
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
    _nested: Final[weakref.WeakValueDictionary[Hashable, "Symbol"]] = field(
        default_factory=weakref.WeakValueDictionary
    )

    def to_relative_reference(
        self,
        reference: "ResourceReference[Hashable]",
    ) -> "RelativeReference[Hashable]":
        """
        Convert a ResourceReference to a RelativeReference for resolution from outer scope.

        The returned RelativeReference should be resolved from self.outer (not from self).

        Analogy with file paths:
        - self = current file `/foo/bar/baz`
        - self.outer = PWD `/foo/bar/`
        - AbsoluteReference `/qux` → RelativeReference `../../qux` (from PWD)

        For RelativeReference: return as-is.
        For AbsoluteReference: levels_up = depth(self.outer) = depth(self) - 1.

        :param reference: The reference to convert.
        :return: A RelativeReference for resolution from self.outer.
        """
        match reference:
            case RelativeReference():
                return reference
            case AbsoluteReference(path=path):
                depth = 0
                current: Symbol = self
                while True:
                    match current.outer:
                        case OuterSentinel.ROOT:
                            break
                        case Symbol() as outer_symbol:
                            depth += 1
                            current = outer_symbol
                return RelativeReference(levels_up=depth - 1, path=path)
            case _ as unreachable:
                assert_never(unreachable)

    def resolve_relative_reference(
        self,
        reference: "RelativeReference[Hashable]",
        expected_type: type[TSymbol],
    ) -> TSymbol:
        """
        Resolve a RelativeReference to a Symbol using this symbol as starting point.

        - Navigate up ``levels_up`` levels from this symbol via ``.outer``
        - Then navigate down through ``path`` using ``symbol[key]``

        :param reference: The RelativeReference describing the path to the target symbol.
        :param expected_type: The expected type of the resolved symbol.
        :return: The resolved symbol of the expected type.
        :raises ValueError: If navigation goes beyond the root symbol.
        :raises TypeError: If intermediate or final resolved value is not of expected type.
        """
        current: Symbol = self
        for level in range(reference.levels_up):
            match current.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Cannot navigate up {reference.levels_up} levels: "
                        f"reached root at level {level}"
                    )
                case Symbol() as outer_scope:
                    current = outer_scope

        for part_index, part in enumerate(reference.path):
            resolved = current[part]
            if not isinstance(resolved, Symbol):
                path_so_far = ".".join(str(p) for p in reference.path[: part_index + 1])
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

    @abstractmethod
    def bind(
        self,
        outer: "Mixin | OuterSentinel",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> TMixin_co:
        """Retrieve the Mixin for the given outer mixin and lexical scope index."""
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
        existing = self._nested.get(key)
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

        self._nested[key] = cast("Symbol", compiled_symbol)
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
    def is_local(self):
        return any(
            super_symbol.definition.is_local
            for super_symbol in chain((self,), self.strict_super_indices)
            if isinstance(super_symbol, DefinedSymbol)
            and isinstance(super_symbol.definition, MergerDefinition)
        )

    @cached_property
    def is_eager(self):
        return any(
            super_symbol.definition.is_eager
            for super_symbol in chain((self,), self.strict_super_indices)
            if isinstance(super_symbol, DefinedSymbol)
            and isinstance(super_symbol.definition, MergerDefinition)
        )

    @cached_property
    def elected_merger_index(
        self,
    ) -> SymbolIndexSentinel | MergerElectionSentinel | int:
        """
        Elect the merger from self and base symbols.

        Implements the merger election algorithm at compile time:
        0. If has DefinedScopeSymbol AND has (PatcherSymbol | MergerSymbol), raises ValueError
        1. If exactly one pure Merger exists, it is elected
        2. If multiple pure Mergers exist, raises ValueError
        3. If no pure Mergers but Semigroup exists, first Semigroup is elected
        4. If no Merger/Semigroup but has Patcher, raises NotImplementedError
        5. If no Merger/Semigroup, no Patcher, but has DefinedScopeSymbol, returns NO_MERGER
        6. Otherwise, raises NotImplementedError

        Returns:
            SymbolIndexSentinel.OWN if self is the elected merger,
            int index if a base symbol is elected,
            MergerElectionSentinel.NO_MERGER if scope symbol with no merger/patcher.
        """

        def generate_self_and_bases():
            yield (SymbolIndexSentinel.OWN, self)
            yield from enumerate(self.strict_super_indices)

        # Collect symbol types for validation
        self_and_bases = tuple(generate_self_and_bases())

        has_scope_symbol = any(
            isinstance(base_symbol, DefinedScopeSymbol)
            for _, base_symbol in self_and_bases
        )
        has_merger_or_patcher = any(
            isinstance(base_symbol, (MergerSymbol, PatcherSymbol))
            for _, base_symbol in self_and_bases
        )

        # Rule 0: DefinedScopeSymbol cannot coexist with MergerSymbol/PatcherSymbol
        if has_scope_symbol and has_merger_or_patcher:
            raise ValueError(
                "DefinedScopeSymbol cannot coexist with MergerSymbol or PatcherSymbol"
            )

        pure_merger_indices = tuple(
            index
            for index, base_symbol in self_and_bases
            if isinstance(base_symbol, MergerSymbol)
            and not isinstance(base_symbol, PatcherSymbol)
        )
        match pure_merger_indices:
            case (single_index,):
                return single_index
            case ():
                semigroup_indices = tuple(
                    index
                    for index, base_symbol in self_and_bases
                    if isinstance(base_symbol, SemigroupSymbol)
                )
                match semigroup_indices:
                    case (first_index, *_):
                        return first_index
                    case ():
                        # No merger and no semigroup, check for patchers
                        has_patcher = any(
                            isinstance(base_symbol, PatcherSymbol)
                            for _, base_symbol in self_and_bases
                        )
                        if has_patcher:
                            return MergerElectionSentinel.PATCHER_ONLY
                        # Check if self or bases contain DefinedScopeSymbol (scope that returns Scope)
                        if has_scope_symbol:
                            return MergerElectionSentinel.SCOPE
                        raise NotImplementedError("No merger definition provided")
            case _:
                raise ValueError("Multiple pure merger definitions found")

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
            case (DefinedSymbol() as defined_symbol, Symbol() as outer_scope):
                return {
                    symbol: NestedSymbolIndex(
                        primary_index=OwnBaseIndex(index=own_base_index),
                        secondary_index=SymbolIndexSentinel.OWN,
                    )
                    for own_base_index, relative_reference in enumerate(
                        defined_symbol.relative_bases
                    )
                    if isinstance(
                        symbol := outer_scope.resolve_relative_reference(
                            relative_reference, Symbol
                        ),
                        DefinedSymbol,
                    )
                }
            case _:
                return {}

    @final
    @cached_property
    def transitive_base_indices(
        self,
    ) -> dict["Symbol", NestedSymbolIndex]:
        match (self, self.outer):
            case (DefinedSymbol() as defined_symbol, Symbol() as outer_scope):
                return {
                    symbol: (
                        NestedSymbolIndex(
                            primary_index=OwnBaseIndex(index=own_base_index),
                            secondary_index=secondary_index,
                        )
                    )
                    for own_base_index, relative_reference in enumerate(
                        defined_symbol.relative_bases
                    )
                    # Linearized strict super symbols of the extend reference
                    for secondary_index, symbol in enumerate(
                        outer_scope.resolve_relative_reference(
                            relative_reference,
                            Symbol,
                        ).generate_strict_super()
                    )
                    if isinstance(
                        symbol,
                        DefinedSymbol,
                    )
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
    def union_own_indices(self):
        """
        Index mapping for outer base classes themselves.

        Maps each outer base class to its ``NestedSymbolIndex`` with
        ``OuterBaseIndex`` as primary and ``SymbolIndexSentinel.OWN`` as secondary.
        """
        return {
            symbol: NestedSymbolIndex(
                primary_index=OuterBaseIndex(index=primary_index),
                secondary_index=SymbolIndexSentinel.OWN,
            )
            for symbol, primary_index in self.union_indices.items()
            if isinstance(symbol, DefinedSymbol)
        }

    @cached_property
    def linearized_union_base_indices(self):
        """
        Index mapping for strict super symbols of outer base classes.

        Maps each strict super symbol from outer base classes to its ``NestedSymbolIndex``
        with ``OuterBaseIndex`` as primary and the linearized index as secondary.
        """
        return {
            symbol: NestedSymbolIndex(
                primary_index=OuterBaseIndex(index=primary_index),
                secondary_index=secondary_index,
            )
            for base, primary_index in self.union_indices.items()
            for secondary_index, symbol in enumerate(base.strict_super_indices)
            if isinstance(symbol, DefinedSymbol)
        }

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
        return ChainMap(self.union_own_indices, self.linearized_union_base_indices)


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

    definition: "Definition"

    @final
    @cached_property
    def relative_bases(self) -> tuple["RelativeReference[Hashable]", ...]:
        """
        Convert definition.bases from ResourceReference to RelativeReference.

        This caches the conversion so that both direct_base_indices and
        transitive_base_indices can reuse the result.
        """
        return tuple(
            self.to_relative_reference(reference)
            for reference in self.definition.bases
        )


class OuterSentinel(Enum):
    """Sentinel value for symbols that have no outer scope (root symbols)."""

    ROOT = auto()


@dataclass(kw_only=True, frozen=True, eq=False)
class Mixin(Mapping[Hashable, "Mixin"], ABC):
    """Base class for Merger, Patcher, and SyntheticResourceMixin."""

    symbol: "Symbol[Self]"

    outer: Mixin | OuterSentinel
    """The outer Mixin or OuterSentinel.ROOT if this is a root Mixin."""

    lexical_outer_index: "SymbolIndexSentinel | int"
    """
    Index to locate the lexical outer scope for dependency resolution.

    - ``SymbolIndexSentinel.OWN``: lexical outer = ``outer``
    - ``int``: lexical outer = ``outer.strict_super_mixins[index]``
    """

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other: object) -> bool:
        return self is other

    def __iter__(self) -> Iterator[Hashable]:
        return iter(self.symbol)

    def __len__(self) -> int:
        return len(self.symbol)

    def __getattr__(self, key: str) -> "Node":
        try:
            child_mixin = self[key]
            return child_mixin.evaluated
        except KeyError as error:
            raise AttributeError(name=key, obj=self) from error

    @override
    def __dir__(self) -> Sequence[str]:
        return (
            *(key for key in self.symbol if isinstance(key, str)),
            *super(Mixin, self).__dir__(),
        )

    def __call__(self, **kwargs: object) -> "InstanceScope":
        """
        Create an instance scope with the provided kwargs.

        Creates a new InstanceScope with the same symbol but with kwargs bound.
        When child resources are accessed, kwargs take precedence over symbol lookups.
        """
        return InstanceScope(
            symbol=self.symbol,
            outer=self.outer,
            lexical_outer_index=self.lexical_outer_index,
            kwargs=kwargs,
        )

    @property
    def lexical_outer(self) -> "Mixin":
        """
        Get the lexical outer scope for dependency resolution.

        The lexical outer is determined by ``lexical_outer_index``:
        - ``SymbolIndexSentinel.OWN``: returns ``outer`` directly, or ``self`` for root mixin
        - ``int``: returns ``outer.strict_super_mixins[index]``
        """
        match self.lexical_outer_index:
            case SymbolIndexSentinel.OWN:
                if isinstance(self.outer, Mixin):
                    return self.outer
                # Root mixin: lexical outer is self (for resolving siblings in root scope)
                return self
            case int() as index:
                assert isinstance(self.outer, Mixin)
                return self.outer.get_super(index)

    def get_super(self, super_index: "SymbolIndexSentinel | int") -> "Mixin":
        """
        Get a super mixin by index.

        :param super_index: The index to look up.
            - ``SymbolIndexSentinel.OWN``: returns ``self``
            - ``int``: returns ``self.strict_super_mixins[index]``
        :return: The super mixin.
        """
        match super_index:
            case SymbolIndexSentinel.OWN:
                return self
            case int() as index:
                return self.strict_super_mixins[index]

    _nested: MutableMapping[Hashable, "Mixin"] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __getitem__(self, key: Hashable) -> "Mixin":
        if key not in self._nested:
            self._nested[key] = self.symbol[key].bind(
                outer=self,
                lexical_outer_index=SymbolIndexSentinel.OWN,
            )
        return self._nested[key]

    @cached_property
    def strict_super_mixins(self) -> Sequence["Mixin"]:
        return tuple(self.generate_strict_super_mixins())

    @cached_property
    def evaluated(self):
        elected_index = self.symbol.elected_merger_index

        # No merger and no patcher - return self directly
        if elected_index is MergerElectionSentinel.SCOPE:
            return self

        def generate_patcher():
            if elected_index != SymbolIndexSentinel.OWN:
                if isinstance(self, Patcher):
                    yield from self
            for index, patcher in enumerate(self.strict_super_mixins):
                if index != elected_index:
                    if isinstance(patcher, Patcher):
                        yield from patcher

        def apply_endofunction(accumulator: object, endofunction: object) -> object:
            if not callable(endofunction):
                raise TypeError(
                    f"Patcher must yield callable endofunctions, got {type(endofunction).__name__}"
                )
            return endofunction(accumulator)

        if elected_index is MergerElectionSentinel.PATCHER_ONLY:
            if not isinstance(self.outer, InstanceScope):
                raise NotImplementedError(
                    f"Patcher-only resource '{self.symbol.key}' requires instance scope"
                )
            key = self.symbol.key
            if not isinstance(key, str) or key not in self.outer.kwargs:
                raise NotImplementedError(
                    f"Patcher-only resource '{key}' requires kwargs"
                )
            return reduce(
                apply_endofunction, generate_patcher(), self.outer.kwargs[key]
            )

        merger = self.get_super(elected_index)
        assert isinstance(merger, Merger)
        return merger.merge(generate_patcher())

    def resolve_relative_reference(
        self,
        reference: "RelativeReference[Hashable]",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "Mixin":
        """
        Resolve a RelativeReference to a Mixin.

        Starting point is ``self.outer`` (the scope where path navigation begins).

        Navigation semantics for each ``levels_up`` step:
        - If ``lexical_outer_index`` is ``OWN``: ``current = current.outer``
        - If ``lexical_outer_index`` is ``int(i)``: ``current = current.strict_super_mixins[i].outer``

        Then navigate down through ``path`` using ``mixin[key]``.

        :param reference: The RelativeReference describing the path to the target mixin.
        :param lexical_outer_index: The lexical outer index of the caller, used for navigation.
        :return: The resolved mixin.
        """
        # Start from self.outer (the parent scope where we search)
        if isinstance(self.outer, Mixin):
            current: Mixin = self.outer
        else:
            current = self  # Root case: stay at self

        current_lexical_index: SymbolIndexSentinel | int = lexical_outer_index

        _logger.debug(
            "resolve_relative_reference: self_key=%(self_key)s reference=%(reference)s "
            "lexical_outer_index=%(lex_idx)s starting_current=%(current_key)s",
            {
                "self_key": self.symbol.key,
                "reference": reference,
                "lex_idx": lexical_outer_index,
                "current_key": current.symbol.key,
            },
        )

        for level in range(reference.levels_up):
            _logger.debug(
                "resolve_relative_reference: level=%(level)s current_key=%(current_key)s "
                "current_lexical_index=%(lex_idx)s",
                {
                    "level": level,
                    "current_key": current.symbol.key,
                    "lex_idx": current_lexical_index,
                },
            )
            # current = current.get_super(lexical_index).outer
            base = current.get_super(current_lexical_index)
            current_lexical_index = base.lexical_outer_index
            assert isinstance(base.outer, Mixin)
            current = base.outer
            _logger.debug(
                "resolve_relative_reference: after_level current_key=%(current_key)s",
                {"current_key": current.symbol.key},
            )

        for part in reference.path:
            _logger.debug(
                "resolve_relative_reference: path_part=%(part)s current_key=%(current_key)s",
                {"part": part, "current_key": current.symbol.key},
            )
            current = current[part]

        _logger.debug(
            "resolve_relative_reference: result_key=%(result_key)s",
            {"result_key": current.symbol.key},
        )
        return current

    def generate_strict_super_mixins(self):
        _logger.debug(
            "generate_strict_super_mixins: self_key=%(self_key)s self_type=%(self_type)s "
            "outer_key=%(outer_key)s strict_super_indices=%(indices)s",
            {
                "self_key": self.symbol.key,
                "self_type": type(self).__name__,
                "outer_key": (
                    self.outer.symbol.key if isinstance(self.outer, Mixin) else "ROOT"
                ),
                "indices": list(self.symbol.strict_super_indices.keys()),
            },
        )
        for nested_index in self.symbol.strict_super_indices.values():
            _logger.debug(
                "generate_strict_super_mixins: processing nested_index=%(nested_index)s",
                {"nested_index": nested_index},
            )
            match nested_index.primary_index:
                case OuterBaseIndex(index=i):
                    assert isinstance(self.outer, Mixin)
                    # Get the base mixin from outer's strict_super_mixins
                    base_mixin = self.outer.get_super(i)
                    _logger.debug(
                        "generate_strict_super_mixins: OuterBaseIndex i=%(i)s base_mixin_key=%(base_key)s",
                        {"i": i, "base_key": base_mixin.symbol.key},
                    )
                    # Create mixin with:
                    # - outer = self.outer (runtime instance)
                    # - lexical_outer_index = i (points to base_mixin in inheritance chain)
                    direct_mixin = base_mixin.symbol[self.symbol.key].bind(
                        outer=self.outer,
                        lexical_outer_index=i,
                    )
                case OwnBaseIndex(index=i):
                    assert isinstance(self.symbol, DefinedSymbol)
                    reference = self.symbol.relative_bases[i]
                    _logger.debug(
                        "generate_strict_super_mixins: OwnBaseIndex i=%(i)s reference=%(reference)s",
                        {"i": i, "reference": reference},
                    )
                    direct_mixin = self.resolve_relative_reference(
                        reference,
                        lexical_outer_index=self.lexical_outer_index,
                    )
                case SymbolIndexSentinel.OWN:
                    direct_mixin = self
            _logger.debug(
                "generate_strict_super_mixins: direct_mixin_key=%(key)s direct_mixin_type=%(type)s",
                {"key": direct_mixin.symbol.key, "type": type(direct_mixin).__name__},
            )
            yield direct_mixin.get_super(nested_index.secondary_index)


class SymbolIndexSentinel(Enum):
    """Sentinel value for symbol indices indicating the symbol itself (not a base)."""

    OWN = auto()


class MergerElectionSentinel(Enum):
    """Sentinel value for merger election"""

    SCOPE = auto()
    """
    Indicates that the symbol is a scope with no merger or patcher.
    """

    PATCHER_ONLY = auto()
    """
    Indicates that the symbol has patchers but no merger (and no scope symbol).
    """


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
        self,
        outer: "Mixin | OuterSentinel",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "Merger[TPatch_contra, TResult_co]":
        """Retrieve the Merger for the given outer scope."""


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
    def bind(
        self,
        outer: "Mixin | OuterSentinel",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "Patcher[TPatch_co]":
        """Retrieve the Patcher for the given outer scope."""


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

    def bind(
        self,
        outer: "Mixin | OuterSentinel",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "Synthetic":
        """Return a Synthetic mixin."""
        return Synthetic(
            symbol=self, outer=outer, lexical_outer_index=lexical_outer_index
        )


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
    def compiled_function(
        self,
    ) -> Callable[["Mixin"], Callable[[Iterator[TPatch_contra]], TResult_co]]:
        """Compiled function that takes a Mixin and returns the aggregation function."""
        definition = cast(
            "FunctionalMergerDefinition[TPatch_contra, TResult_co]", self.definition
        )
        assert isinstance(
            self.key, str
        ), f"Merger key must be a string, got {type(self.key)}"
        match self.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have compiled functions")
            case Symbol() as outer_symbol:
                return _compile_function_with_mixin(
                    outer_symbol, definition.function, self.key
                )

    def bind(
        self,
        outer: "Mixin | OuterSentinel",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "FunctionalMerger[TPatch_contra, TResult_co]":
        return FunctionalMerger(
            symbol=self, outer=outer, lexical_outer_index=lexical_outer_index
        )


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
    def compiled_function(self) -> Callable[["Mixin"], TResult]:
        """Compiled function that takes a Mixin and returns the base value."""
        definition = cast("EndofunctionMergerDefinition[TResult]", self.definition)
        assert isinstance(
            self.key, str
        ), f"Resource key must be a string, got {type(self.key)}"
        match self.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have compiled functions")
            case Symbol() as outer_scope:
                return _compile_function_with_mixin(
                    outer_scope,
                    definition.function,
                    self.key,
                )

    def bind(
        self,
        outer: "Mixin | OuterSentinel",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "EndofunctionMerger[TResult]":
        return EndofunctionMerger(
            symbol=self, outer=outer, lexical_outer_index=lexical_outer_index
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class SinglePatcherSymbol(DefinedSymbol, PatcherSymbol[TPatch_co], Generic[TPatch_co]):
    """NestedSymbol for _SinglePatchDefinition."""

    @cached_property
    def compiled_function(self) -> Callable[["Mixin"], TPatch_co]:
        """Compiled function that takes a Mixin and returns the patch value."""
        definition = cast("SinglePatcherDefinition[TPatch_co]", self.definition)
        assert isinstance(
            self.key, str
        ), f"Patch key must be a string, got {type(self.key)}"
        match self.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have compiled functions")
            case Symbol() as outer_scope:
                return _compile_function_with_mixin(
                    outer_scope,
                    definition.function,
                    self.key,
                )

    def bind(
        self,
        outer: "Mixin | OuterSentinel",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "SinglePatcher[TPatch_co]":
        return SinglePatcher(
            symbol=self, outer=outer, lexical_outer_index=lexical_outer_index
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class MultiplePatcherSymbol(
    DefinedSymbol, PatcherSymbol[TPatch_co], Generic[TPatch_co]
):
    """NestedSymbol for _MultiplePatchDefinition."""

    @cached_property
    def compiled_function(self) -> Callable[["Mixin"], Iterable[TPatch_co]]:
        """Compiled function that takes a Mixin and returns the patch values."""
        definition = cast("MultiplePatcherDefinition[TPatch_co]", self.definition)
        assert isinstance(
            self.key, str
        ), f"Patch key must be a string, got {type(self.key)}"
        match self.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have compiled functions")
            case Symbol() as outer_scope:
                return _compile_function_with_mixin(
                    outer_scope,
                    definition.function,
                    self.key,
                )

    def bind(
        self,
        outer: "Mixin | OuterSentinel",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "MultiplePatcher[TPatch_co]":
        return MultiplePatcher(
            symbol=self, outer=outer, lexical_outer_index=lexical_outer_index
        )


class SemigroupSymbol(
    MergerSymbol[T, T], PatcherSymbol[T], Symbol["Semigroup[T]"], Generic[T]
):
    """
    Marker base class for Symbols that return a Semigroup (both Merger and Patcher).

    Inherits from ``MergerSymbol`` so that ``isinstance(symbol, MergerSymbol)``
    returns True, which is needed for ``elected_merger_index`` to recognize
    scope symbols as valid merger candidates.

    Use ``isinstance(mixin, SemigroupSymbol)`` to check if a mixin returns
    an evaluator that is both Merger and Patcher (e.g., ``Scope``).

    Subclass: ``DefinedScopeSymbol``.
    """

    @abstractmethod
    def bind(
        self,
        outer: "Mixin | OuterSentinel",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "Semigroup[T]":
        """Retrieve the Semigroup for the given outer scope."""


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class DefinedScopeSymbol(DefinedSymbol, Symbol["StaticScope"]):
    """
    Scope symbol for defined scopes (has local definition with extend references).

    Defined mixins are created when a nested scope has a local definition in the current
    scope. They use the scope class from the definition and include extend references.

    Note: This is NOT a SemigroupSymbol because Scope is not a Merger/Patcher.
    When evaluated, Mixin.evaluated will return self via MergerElectionSentinel.SCOPE path.
    """

    definition: "_ScopeDefinition"

    def bind(
        self,
        outer: "Mixin | OuterSentinel",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "StaticScope":
        """Resolve resources including extend references from definition."""
        return StaticScope(
            symbol=self, outer=outer, lexical_outer_index=lexical_outer_index
        )


Resource = NewType("Resource", object)


Node: TypeAlias = Resource | Mixin


class Merger(Mixin, Generic[TPatch_contra, TResult_co]):
    @abstractmethod
    def merge(self, patches: Iterator[TPatch_contra]) -> TResult_co: ...


class Patcher(Mixin, Iterable[TPatch_co], Generic[TPatch_co]):
    """
    An Patcher provides extra data to be applied to a Node created by a ``Merger``.
    """


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class FunctionalMerger(Merger[TPatch_contra, TResult_co]):
    """Mixin for _NestedMergerSymbol."""

    symbol: "FunctionalMergerSymbol[TPatch_contra, TResult_co]"

    def merge(self, patches: Iterator[TPatch_contra]) -> TResult_co:
        assert isinstance(self.outer, Mixin)
        aggregation_function = self.symbol.compiled_function(self)
        return aggregation_function(patches)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class EndofunctionMerger(Merger["Endofunction[TResult]", TResult]):
    """Mixin for _EndofunctionSymbol."""

    symbol: "EndofunctionMergerSymbol[TResult]"

    def merge(self, patches: Iterator["Endofunction[TResult]"]) -> TResult:
        assert isinstance(self.outer, Mixin)
        base_value = self.symbol.compiled_function(self)
        return reduce(
            lambda accumulator, endofunction: endofunction(accumulator),
            patches,
            base_value,
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class SinglePatcher(Patcher[TPatch_co]):
    """Mixin for _SinglePatchSymbol."""

    symbol: "SinglePatcherSymbol[TPatch_co]"

    def __iter__(self) -> Iterator[TPatch_co]:
        assert isinstance(self.outer, Mixin)
        yield self.symbol.compiled_function(self)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class MultiplePatcher(Patcher[TPatch_co]):
    """Mixin for _NestedMultiplePatchSymbol."""

    symbol: "MultiplePatcherSymbol[TPatch_co]"

    def __iter__(self) -> Iterator[TPatch_co]:
        assert isinstance(self.outer, Mixin)
        yield from self.symbol.compiled_function(self)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class Synthetic(Mixin):
    """
    Mixin for SyntheticSymbol.

    This is NOT a Patcher or Merger. It is excluded from merger election
    because it doesn't satisfy ``isinstance(item, Merger)`` or
    ``isinstance(item, Patcher)`` in ``_evaluate_resource``.
    """

    symbol: "SyntheticSymbol"


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
@dataclass(kw_only=True, frozen=True, slots=True, weakref_slot=True)
class StaticScope(Mixin):
    """
    Mixin for static scope access (no kwargs).

    Used when accessing scopes without instance parameters.
    """

    symbol: "DefinedScopeSymbol"


@final
@dataclass(kw_only=True, frozen=True, slots=True, weakref_slot=True)
class InstanceScope(Mixin):
    """
    Mixin for instance scope access (with kwargs).

    Used when accessing scopes with instance parameters provided via Mixin.__call__(**kwargs).
    When evaluated, patcher-only resources use kwargs values as base values.
    """

    kwargs: Mapping[str, object]


Scope: TypeAlias = StaticScope | InstanceScope


TSymbol = TypeVar("TSymbol", bound=Symbol)


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

    @override
    def __iter__(self) -> Iterator[Hashable]:
        yield from super(_PackageScopeDefinition, self).__iter__()

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

    Example - Union mounting multiple scopes using @extend::

        Use ``@extend`` with ``RelativeReference`` to combine multiple scopes.
        This is the recommended way to create union mount points::

            from mixinject import RelativeReference as R

            @scope
            class Root:
                @scope
                class Branch1:
                    @resource
                    def foo() -> str:
                        return "foo"

                @scope
                class Branch2:
                    @extern
                    def foo(): ...

                    @resource
                    def bar(foo: str) -> str:
                        return f"{foo}_bar"

                @extend(
                    R(levels_up=0, path=("Branch1",)),
                    R(levels_up=0, path=("Branch2",)),
                )
                @scope
                class Combined:
                    pass

            root = evaluate(Root)
            root.Combined.foo  # "foo"
            root.Combined.bar  # "foo_bar"

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

    Example - Extending a sibling scope::

        from mixinject import RelativeReference as R

        @scope
        class Root:
            @scope
            class Base:
                @resource
                def value() -> int:
                    return 10

            @extend(R(levels_up=0, path=("Base",)))
            @scope
            class Extended:
                @patch
                def value() -> Callable[[int], int]:
                    return lambda x: x + 1

        root = evaluate(Root)
        root.Extended.value  # 11

    Example - Extending sibling modules in a package::

        When a package contains multiple modules, use ``@extend`` in
        ``__init__.py`` to combine them::

            # my_package/branch1.py
            @resource
            def foo() -> str:
                return "foo"

            # my_package/branch2.py
            @extern
            def foo(): ...

            @resource
            def bar(foo: str) -> str:
                return f"{foo}_bar"

            # my_package/__init__.py
            from mixinject import RelativeReference as R, extend, scope

            @extend(
                R(levels_up=0, path=("branch1",)),
                R(levels_up=0, path=("branch2",)),
            )
            @scope
            class combined:
                pass

            # Usage:
            # root = evaluate(my_package)
            # root.combined.foo  # "foo"
            # root.combined.bar  # "foo_bar"

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

    The following example defines a merge that deduplicates strings from multiple patches into a frozenset::

        from mixinject import merge, patch, resource, extend, scope, evaluate, extern
        from mixinject import RelativeReference as R

        @scope
        class Root:
            @scope
            class Branch0:
                @merge
                def deduplicated_tags():
                    return frozenset[str]

            @scope
            class Branch1:
                @patch
                def deduplicated_tags():
                    return "tag1"

                @resource
                def another_dependency() -> str:
                    return "dependency_value"

            @scope
            class Branch2:
                @extern
                def another_dependency(): ...

                @patch
                def deduplicated_tags(another_dependency):
                    return f"tag2_{another_dependency}"

            @extend(
                R(levels_up=0, path=("Branch0",)),
                R(levels_up=0, path=("Branch1",)),
                R(levels_up=0, path=("Branch2",)),
            )
            @scope
            class Combined:
                pass

        root = evaluate(Root)
        root.Combined.deduplicated_tags  # frozenset(("tag1", "tag2_dependency_value"))

    Note: For combining multiple scopes, use ``@extend`` with ``RelativeReference``.
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
    Resolves a StaticScope from the given object.

    :param namespace: Module or namespace definition (decorated with @scope) to resolve resources from.
    :return: The root StaticScope.

    Example::

        root = evaluate(MyNamespace)

    """
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
    root_mixin = root_symbol.bind(
        outer=OuterSentinel.ROOT,
        lexical_outer_index=SymbolIndexSentinel.OWN,
    )
    return root_mixin


def _get_param_relative_reference(
    param_name: str, outer_symbol: Symbol
) -> "RelativeReference[Hashable] | RelativeReferenceSentinel":
    """
    Get a RelativeReference to a parameter using lexical scoping (Symbol chain).

    Traverses up the Symbol chain to find the parameter, counting levels.
    Returns a RelativeReference that can be resolved from any Mixin bound to outer_symbol,
    or RelativeReferenceSentinel.NOT_FOUND if the parameter is not found.

    :param param_name: The name of the parameter to find.
    :param outer_symbol: The Symbol to start searching from (lexical scope).
    :return: RelativeReference describing how to reach the parameter,
             or RelativeReferenceSentinel.NOT_FOUND if not found.
    """
    levels_up = 0
    current: Symbol = outer_symbol
    while True:
        if param_name in current:
            return RelativeReference(levels_up=levels_up, path=(param_name,))
        match current.outer:
            case OuterSentinel.ROOT:
                return RelativeReferenceSentinel.NOT_FOUND
            case Symbol() as outer_scope:
                levels_up += 1
                current = outer_scope


def _compile_function_with_mixin(
    outer_symbol: Symbol,
    function: Callable[P, T],
    name: str,
) -> Callable[[Mixin], T]:
    """
    Compile a function with pre-computed dependency references (lexical scoping).

    Returns a function that takes a Mixin and:
    1. Resolves dependencies using pre-computed RelativeReferences
    2. Calls the original function with resolved dependencies

    :param outer_symbol: The Symbol containing the resource (lexical scope).
    :param function: The function for which to resolve dependencies.
    :param name: The name of the resource being resolved (for self-dependency avoidance).
    :return: A function that takes a Mixin and returns the result.
    """
    sig = signature(function)
    params = tuple(sig.parameters.values())
    match params:
        case (first_param, *keyword_params) if (
            first_param.kind == first_param.POSITIONAL_ONLY
        ):
            has_positional = True
        case keyword_params:
            has_positional = False

    # Pre-compute RelativeReferences for each dependency (lexical scoping)
    def compute_dependency_reference(
        parameter: Parameter,
    ) -> tuple[str, RelativeReference[Hashable], int]:
        if parameter.name == name:
            # Same-name dependency: start search from outer_symbol.outer (lexical)
            match outer_symbol.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Same-name dependency '{name}' at root level is not allowed"
                    )
                case Symbol() as search_symbol:
                    pass
            relative_reference_or_sentinel = _get_param_relative_reference(
                parameter.name, search_symbol
            )
            match relative_reference_or_sentinel:
                case RelativeReferenceSentinel.NOT_FOUND:
                    raise LookupError(
                        f"Resource '{name}' depends on '{parameter.name}' "
                        f"which does not exist in scope"
                    )
                case RelativeReference() as relative_reference:
                    # Mark that we need to go up one extra level in Mixin chain
                    return (parameter.name, relative_reference, 1)
        else:
            # Normal dependency
            relative_reference_or_sentinel = _get_param_relative_reference(
                parameter.name, outer_symbol
            )
            match relative_reference_or_sentinel:
                case RelativeReferenceSentinel.NOT_FOUND:
                    raise LookupError(
                        f"Resource '{name}' depends on '{parameter.name}' "
                        f"which does not exist in scope"
                    )
                case RelativeReference() as relative_reference:
                    return (parameter.name, relative_reference, 0)

    dependency_references = tuple(
        compute_dependency_reference(parameter) for parameter in keyword_params
    )

    # Return a compiled function that resolves dependencies at runtime
    def compiled_wrapper(mixin: Mixin) -> T:
        resolved_kwargs: dict[str, object] = {}
        for param_name, ref, extra_levels in dependency_references:
            # Navigate up extra levels via lexical_outer chain (for same-name dependencies)
            search_mixin: Mixin = mixin
            for _ in range(extra_levels):
                search_mixin = search_mixin.lexical_outer
            param_mixin = search_mixin.resolve_relative_reference(
                ref,
                lexical_outer_index=search_mixin.lexical_outer_index,
            )
            resolved_kwargs[param_name] = param_mixin.evaluated

        return function(**resolved_kwargs)  # type: ignore

    def compiled_wrapper_with_positional(mixin: Mixin) -> Callable[..., T]:
        resolved_kwargs: dict[str, object] = {}
        for param_name, ref, extra_levels in dependency_references:
            # Navigate up extra levels via lexical_outer chain (for same-name dependencies)
            search_mixin: Mixin = mixin
            for _ in range(extra_levels):
                search_mixin = search_mixin.lexical_outer
            param_mixin = search_mixin.resolve_relative_reference(
                ref,
                lexical_outer_index=search_mixin.lexical_outer_index,
            )
            resolved_kwargs[param_name] = param_mixin.evaluated

        def inner(positional_arg: object, /) -> T:
            return function(positional_arg, **resolved_kwargs)  # type: ignore

        return inner

    if has_positional:
        return compiled_wrapper_with_positional  # type: ignore
    else:
        return compiled_wrapper


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

.. todo:: Drop the type parameter T, enforce Hashable keys only.

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

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

    from mixinject import scope, resource, patch, evaluate

    @scope
    class Base:
        # ✓ CORRECT: Explicitly decorated
        @resource
        def greeting() -> str:
            return "Hello"

        # ✗ INCORRECT: Bare callable (will be ignored)
        def ignored_function() -> str:
            return "This won't be injected"

    @scope
    class Patches:
        @patch
        def greeting() -> Callable[[str], str]:
            return lambda s: s + "!"

    # Union mount: combine Base and Patches via evaluate()
    root = evaluate(Base, Patches)
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

           @scope
           class SetupA:
               @phony
               def setup():
                   register_handler_a()  # Must be independent from other setup side effects

           @scope
           class SetupB:
               @phony
               def setup():
                   register_handler_b()  # Must be independent from other setup side effects

           # Union mount combines both setup definitions
           root = evaluate(SetupA, SetupB)

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
To combine definitions, use separate scopes and ``evaluate()`` for union mounting.
Common patterns:

**Resource + Patches** (most common)::

    @scope
    class Base:
        @resource
        def value() -> int:
            return 10

    @scope
    class Patches:
        @patch
        def value() -> Callable[[int], int]:
            return lambda x: x * 2

    root = evaluate(Base, Patches)
    root.value  # 20 (base value 10 transformed by patch)

**Merger + Patches** (custom aggregation)::

    @scope
    class MergerScope:
        @merge
        def tags() -> type[frozenset]:
            return frozenset

    @scope
    class Patch1:
        @patch
        def tags() -> str:
            return "tag1"

    @scope
    class Patch2:
        @patch
        def tags() -> str:
            return "tag2"

    root = evaluate(MergerScope, Patch1, Patch2)
    root.tags  # frozenset({"tag1", "tag2"})

**Multiple Scopes** (different resources)::

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

    root = evaluate(Base, Extension)
    # root has both foo and bar resources

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
from collections import defaultdict
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import cached_property
import importlib
import importlib.util
from inspect import Parameter, signature
import itertools
import logging
import os

logger = logging.getLogger(__name__)
from pathlib import Path, PurePath
import pkgutil
from types import ModuleType
from typing import (
    TYPE_CHECKING,
    AbstractSet,
    Any,
    AsyncContextManager,
    Awaitable,
    Callable,
    ChainMap,
    Collection,
    ContextManager,
    Final,
    Generic,
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    ParamSpec,
    Sequence,
    Tuple,
    TypeAlias,
    TypeVar,
    cast,
    final,
    override,
    assert_never,
)


if TYPE_CHECKING:
    from mixinject import runtime
    from mixinject.mixin_parser import FileMixinDefinition


import weakref

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


class Symbol(ABC):
    pass


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True)
class Nested:
    """Represents a nested symbol that hasn't resolved its definitions yet.

    ``outer`` is the structural parent (the symbol whose ``__getitem__`` created this).
    """

    outer: "MixinSymbol"
    key: Hashable


@dataclass(kw_only=True, eq=False)
class MixinSymbol(HasDict, Mapping[Hashable, "MixinSymbol"], Symbol):
    """
    Base class for nodes in the dependency graph.

    All symbols support the Mapping interface (``__getitem__``, ``__iter__``, ``__len__``).
    Scope symbols have nested resources (len > 0), while leaf symbols have no items (len = 0).

    Conceptual Layer Distinction
    ============================

    This system has three distinct layers:

    **Symbol Layer (Compile-time Dependency Graph)**

    - ``Symbol`` (ABC): Base abstract class for all symbols
    - ``MixinSymbol``: Concrete node in dependency graph, implements ``Mapping[Hashable, MixinSymbol]``
    - ``EvaluatorSymbol``: Abstract symbol that produces an ``Evaluator`` when bound to a ``Mixin``
      - ``MergerSymbol``: Produces ``Merger`` evaluators
      - ``PatcherSymbol``: Produces ``Patcher`` evaluators
      - ``SemigroupSymbol``: Both ``MergerSymbol`` and ``PatcherSymbol``

    **Node Layer (Runtime Objects)**

    - ``Node`` (ABC): Base class for runtime objects in the dependency injection graph
      - ``Mixin`` (ABC): Base for merged results (determined by ``symbol.mixin_type``)
        - ``Scope`` (ABC): Container for nested resources, implements ``Mapping``
          - ``StaticScope``: Scope created from ``@scope`` decorated classes
          - ``InstanceScope``: Scope created by calling a scope with arguments
        - ``Resource``: Leaf node, evaluates to a value via ``evaluated`` property
      - ``Evaluator``: Transformation that composes a resource (merger or patcher)
        - ``Merger``: Merges patches to produce a result
        - ``Patcher``: Provides patches to be merged
        - ``Semigroup``: Both ``Merger`` and ``Patcher`` (commutative composition)

    Class Hierarchies
    =================

    Symbol Hierarchy::

        Symbol (ABC)
        ├── MixinSymbol (Mapping[Hashable, MixinSymbol])
        │       Concrete dependency graph node
        │       __getitem__(key) → MixinSymbol
        │
        └── EvaluatorSymbol[TEvaluator] (Generic)
                bind(mixin) → TEvaluator
                │
                ├── MergerSymbol[TPatch, TResult]
                │   │   bind(mixin) → Merger[TPatch, TResult]
                │   │
                │   ├── FunctionalMergerSymbol
                │   ├── EndofunctionMergerSymbol
                │   └── SemigroupSymbol (also PatcherSymbol)
                │
                └── PatcherSymbol[TPatch]
                        bind(mixin) → Patcher[TPatch]
                        │
                        ├── SinglePatcherSymbol
                        ├── MultiplePatcherSymbol
                        └── SemigroupSymbol (also MergerSymbol)

    Definition Hierarchy::

        Definition (ABC)
        │
        ├── EvaluatorDefinition (ABC)
        │   │   compile(symbol) → EvaluatorSymbol
        │   │
        │   ├── MergerDefinition
        │   │   ├── FunctionalMergerDefinition  → FunctionalMergerSymbol
        │   │   └── EndofunctionMergerDefinition → EndofunctionMergerSymbol
        │   │
        │   └── PatcherDefinition
        │       ├── SinglePatcherDefinition → SinglePatcherSymbol
        │       └── MultiplePatcherDefinition → MultiplePatcherSymbol
        │
        └── ScopeDefinition (no compile method)
            └── PackageScopeDefinition

    Node Hierarchy (Runtime)::

        Node (ABC) - Runtime objects in dependency graph
        │
        ├── Mixin (ABC) - Base for merged results
        │   │   symbol.mixin_type → type[Mixin]
        │   │
        │   ├── Scope (ABC, Mapping[Hashable, Mixin]) - Container
        │   │   │   __getitem__(key) → Mixin
        │   │   │   __getattr__(key) → Mixin | object
        │   │   │
        │   │   ├── StaticScope (@final)
        │   │   └── InstanceScope (@final, has kwargs)
        │   │
        │   └── Resource (@final) - Leaf node
        │           evaluators → tuple[Evaluator, ...]
        │           evaluated → object
        │
        └── Evaluator (ABC) - Transformation component
            ├── Merger[TPatch, TResult]
            │   │   merge(patches: Iterator[TPatch]) → TResult
            │   │
            │   ├── FunctionalMerger
            │   ├── EndofunctionMerger
            │   └── Semigroup (also Patcher)
            │
            └── Patcher[TPatch] (Iterable[TPatch])
                    __iter__() → Iterator[TPatch]
                │
                ├── SinglePatcher
                ├── MultiplePatcher
                └── Semigroup (also Merger)

    Definition to EvaluatorSymbol Mapping
    =====================================

    ============================== ============================ ============================
    Definition Type                Compiled EvaluatorSymbol     Evaluator Type
    ============================== ============================ ============================
    ``FunctionalMergerDefinition`` ``FunctionalMergerSymbol``   ``FunctionalMerger``
    ``EndofunctionMergerDefinition`` ``EndofunctionMergerSymbol`` ``EndofunctionMerger``
    ``SinglePatcherDefinition``    ``SinglePatcherSymbol``      ``SinglePatcher``
    ``MultiplePatcherDefinition``  ``MultiplePatcherSymbol``    ``MultiplePatcher``
    ``ScopeDefinition``            (no EvaluatorSymbol)         (creates nested MixinSymbol)
    ============================== ============================ ============================

    .. todo:: Mixin and Scope Redesign

       Implement a new ``Mixin`` and ``Scope`` design to properly support
       ``is_local`` and ``is_eager`` semantics.

       **Mixin (Lazy Evaluation Layer)**

       - ``Mixin`` can be lazily evaluated to produce either a ``Resource`` or a ``Scope``
       - ``Mixin`` may be a dynamically generated class
       - ``Mixin`` is NOT frozen (mutable)
       - All lazy evaluation occurs at the ``Mixin.evaluated`` level

       **Scope (Frozen Data Container)**

       - ``Scope`` is a frozen, dynamically generated dataclass
       - ``Scope`` does NOT inherit from ``Mixin``
       - ``Scope`` has NO lazy evaluation capability at the attribute level
       - All attributes are eagerly resolved when the ``Scope`` instance is created

       **Circular Dependencies Between Mixin Instances**

       ``Mixin`` instances under the same ``Scope`` can have circular dependencies.
       This is achieved through a two-phase construction:

       1. First, construct all ``Mixin`` instances without arguments (empty initialization)
       2. Then, mutually set references by assigning each ``Mixin`` instance to the
          appropriate attributes of the others

       This pattern requires ``Mixin`` to be mutable (not frozen), enabling the deferred
       wiring of circular references after initial construction.

       **Key Difference from Current Design**

       The current ``Scope`` implements lazy evaluation at the attribute level (each field
       is lazily evaluated via descriptors). This duplicates the lazy evaluation already
       provided by ``Mixin``'s single-value lazy evaluation, resulting in redundant and
       inelegant design.

       In the new design:

       - Lazy evaluation happens ONLY at the ``Mixin.evaluated`` boundary
       - ``Scope`` attributes are NOT lazily evaluated
       - This eliminates the redundancy and provides a cleaner separation of concerns
    """

    origin: Nested | Sequence["Definition"]
    """
    Origin of this symbol:
    - For root symbols: Sequence[Definition] (the definitions directly)
    - For nested symbols: Nested(outer, key) (lazy resolution)
    """

    _nested: weakref.WeakValueDictionary[Hashable, "MixinSymbol"] = field(
        default_factory=weakref.WeakValueDictionary
    )

    @property
    def outer(self) -> "MixinSymbol | OuterSentinel":
        """Get the structural parent symbol (the symbol that contains this one in the tree).

        For nested symbols, this is the symbol whose ``__getitem__`` created this symbol.
        For root symbols, returns ``OuterSentinel.ROOT``.

        This corresponds to ``Mixin.outer`` at runtime.
        """
        match self.origin:
            case Nested(outer=outer):
                return outer
            case _:
                return OuterSentinel.ROOT

    @property
    def key(self) -> Hashable:
        """Get the key, inferred from origin."""
        match self.origin:
            case Nested(key=key):
                return key
            case _:
                return KeySentinel.ROOT

    @property
    def path(self) -> tuple[Hashable, ...]:
        """Get the full path from root to this symbol, excluding root itself.

        For example, ``Foo.Bar.Baz`` produces::

            ("Foo", "Bar", "Baz")
        """
        segments: list[Hashable] = []
        current: MixinSymbol | OuterSentinel = self
        while isinstance(current, MixinSymbol):
            match current.origin:
                case Nested(outer=outer, key=key):
                    segments.append(key)
                    current = outer
                case _:
                    break
        segments.reverse()
        return tuple(segments)

    @property
    def attribute_name(self) -> str:
        """Generate a unique attribute name for caching this symbol's mixin on outer scope."""
        key_str = str(self.key)
        sanitized = "".join(
            char if char.isalnum() or char == "_" else "_" for char in key_str
        )
        return f"_mixin_cache_{sanitized}_{id(self):x}"

    @cached_property
    def definitions(self) -> tuple["Definition", ...]:
        """Definitions for this MixinSymbol. Can be 0, 1, or multiple.

        TODO: Rename to ``own_definitions`` to clarify that this only returns
        definitions directly on this symbol, not inherited from bases/supers.
        Inherited definitions should be accessed via ``cached_transitive_references``.
        """
        match self.origin:
            case Nested(outer=outer, key=key):
                return tuple(
                    inner_def
                    for definition in outer.definitions
                    if isinstance(definition, ScopeDefinition)
                    for inner_def in (definition.get(key) or ())
                )
            case definitions:
                return tuple(definitions)

    @final
    @cached_property
    def resolved_bases(self) -> tuple["ResolvedReference", ...]:
        """
        Flatten all bases from all definitions into a single tuple.
        Convert from ResourceReference to ResolvedReference with pre-resolved symbols.

        De Bruijn indices are computed from the definition-site lexical scope (self).
        Callers provide composition-site ``current``/``current_lexical`` to
        ``get_symbol``/``get_mixin`` for late-binding reparenting.
        """
        return tuple(
            reference.resolve(self)
            for definition in self.definitions
            for reference in definition.bases
        )

    @final
    @cached_property
    def evaluator_symbols(self) -> tuple["EvaluatorSymbol", ...]:
        """
        Lazily create EvaluatorSymbols from definitions.

        Calls definition.compile(self) for each EvaluatorDefinition.
        ScopeDefinition is skipped as it doesn't produce EvaluatorSymbols.
        """
        return tuple(
            definition.compile(self)
            for definition in self.definitions
            if isinstance(definition, EvaluatorDefinition)
        )

    @final
    @cached_property
    def same_scope_dependencies(self) -> tuple["MixinSymbol", ...]:
        """
        Get all same-scope dependencies from all evaluator symbols.

        Aggregates get_same_scope_dependencies() from all evaluator symbols,
        deduplicating by attribute_name. Used by V2's construct_scope
        for wiring _sibling_dependencies.
        """
        seen: set[str] = set()  # Use attribute_name to dedupe
        result: list[MixinSymbol] = []
        for evaluator_symbol in self.evaluator_symbols:
            for dependency in evaluator_symbol.get_same_scope_dependencies():
                if dependency.attribute_name not in seen:
                    seen.add(dependency.attribute_name)
                    result.append(dependency)
        return tuple(result)

    def resolve_relative_reference(
        self,
        reference: "RelativeReference",
        expected_type: type[TSymbol],
    ) -> TSymbol:
        """
        Resolve a RelativeReference to a MixinSymbol using this symbol as starting point.

        - Navigate up ``de_bruijn_index`` levels from this symbol via ``.outer``
        - Then navigate down through ``path`` using ``symbol[key]``

        :param reference: The RelativeReference describing the path to the target symbol.
        :param expected_type: The expected type of the resolved symbol.
        :return: The resolved symbol of the expected type.
        :raises ValueError: If navigation goes beyond the root symbol.
        :raises TypeError: If intermediate or final resolved value is not of expected type.
        """
        current: MixinSymbol = self
        for level in range(reference.de_bruijn_index):
            match current.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Cannot navigate up {reference.de_bruijn_index} levels: "
                        f"reached root at level {level}"
                    )
                case MixinSymbol() as outer_scope:
                    current = outer_scope

        for part_index, part in enumerate(reference.path):
            resolved = current[part]
            if not isinstance(resolved, MixinSymbol):
                path_so_far = ".".join(str(p) for p in reference.path[: part_index + 1])
                raise TypeError(
                    f"Expected MixinSymbol while resolving reference, "
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

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other: object) -> bool:
        return self is other

    def has_own_key(self, key: Hashable) -> bool:
        """Check if key exists in own definitions (strict lexical scope).

        Only checks keys defined directly in this symbol's definitions,
        not keys inherited from bases. Used for strict lexical scoping.
        """
        for definition in self.definitions:
            if isinstance(definition, ScopeDefinition) and key in definition:
                return True
        return False

    def __iter__(self) -> Iterator[Hashable]:
        """Iterate over keys in this symbol.

        For scope symbols, yields keys from definition and bases.
        For leaf symbols, yields nothing (empty iterator).
        """
        seen: set[Hashable] = set()

        # Keys from own definitions (only ScopeDefinition has keys)
        for definition in self.definitions:
            if isinstance(definition, ScopeDefinition):
                for key in definition:
                    if key not in seen:
                        seen.add(key)
                        yield key

        # Keys from super unions (own definitions only, no recursion)
        for super_union in self.super_unions:
            for definition in super_union.definitions:
                if isinstance(definition, ScopeDefinition):
                    for key in definition:
                        if key not in seen:
                            seen.add(key)
                            yield key

    def __len__(self) -> int:
        """Return the number of keys in this symbol."""
        return sum(1 for _ in self)

    def __getitem__(self, key: Hashable) -> "MixinSymbol":
        """Get or create the child MixinSymbol for the specified key.

        For scope symbols, compiles and caches nested symbols.
        For leaf symbols, raises KeyError.
        """
        existing = self._nested.get(key)
        if existing is not None:
            return existing

        # Leaf symbol (Resource) - no nested items
        if not self.is_scope:
            raise KeyError(key)

        # Use Nested to create child symbol with lazy definition resolution
        compiled_symbol = MixinSymbol(origin=Nested(outer=self, key=key))

        # Check if any super union of self has this key as an own key
        if not any(super_union.has_own_key(key) for super_union in self.super_unions):
            raise KeyError(key)

        self._nested[key] = compiled_symbol
        return compiled_symbol

    @property
    def depth(self) -> int:
        """Return the depth of this symbol in the scope hierarchy.

        The de_bruijn_index represents the static nesting depth of the symbol:
        - Root symbols (outer=OuterSentinel.ROOT) have depth 0.
        - Nested symbols have depth = outer.depth + 1.
        """
        match self.outer:
            case OuterSentinel.ROOT:
                return 0
            case MixinSymbol() as outer_symbol:
                return outer_symbol.depth + 1

    @cached_property
    def is_public(self):
        # Check if any definition is public
        return any(
            definition.is_public
            for super_symbol in self.super_unions
            for definition in super_symbol.definitions
        )

    @cached_property
    def is_eager(self):
        return any(
            definition.is_eager
            for super_symbol in self.super_unions
            for definition in super_symbol.definitions
            if isinstance(definition, MergerDefinition)
        )

    @cached_property
    def is_scope(self) -> bool:
        """
        Returns True if this symbol evaluates to a scope.

        A symbol is a scope if all definitions (own and super) are ScopeDefinition.
        """
        all_definitions = tuple(
            definition
            for symbol in self.super_unions
            for definition in symbol.definitions
        )
        if not all_definitions:
            return False
        return all(
            isinstance(definition, ScopeDefinition) for definition in all_definitions
        )

    @cached_property
    def elected_merger_index(
        self,
    ) -> "ElectedMerger | MergerElectionSentinel":
        """
        Elect the merger from self and base symbols.

        Iterates over all symbols and their evaluator_symbols to find:
        1. Pure mergers (MergerSymbol but not PatcherSymbol)
        2. Semigroups (both MergerSymbol and PatcherSymbol)
        3. Pure patchers (PatcherSymbol only)

        Returns:
            ElectedMerger: Position of the elected MergerSymbol
            MergerElectionSentinel.PATCHER_ONLY: Has patchers but no merger
        """

        self_and_strict_supers = tuple(self.super_unions)

        # Collect all (symbol, evaluator_getter_index, getter) tuples
        all_merger_symbols: list[tuple["MixinSymbol", int, "MergerSymbol"]] = []
        all_patcher_symbols: list[tuple["MixinSymbol", int, "PatcherSymbol"]] = []

        for symbol in self_and_strict_supers:
            for getter_index, getter in enumerate(symbol.evaluator_symbols):
                if isinstance(getter, MergerSymbol):
                    all_merger_symbols.append((symbol, getter_index, getter))
                if isinstance(getter, PatcherSymbol):
                    all_patcher_symbols.append((symbol, getter_index, getter))

        # Check for scope symbols (definitions containing ScopeDefinition)
        has_scope_symbol = any(
            any(isinstance(d, ScopeDefinition) for d in symbol.definitions)
            for symbol in self_and_strict_supers
        )

        # Rule 0: Scope MixinSymbol cannot coexist with MergerSymbol/PatcherSymbol
        if has_scope_symbol and (all_merger_symbols or all_patcher_symbols):
            raise ValueError(
                "Scope MixinSymbol cannot coexist with MergerSymbol or PatcherSymbol"
            )

        # Find pure mergers (MergerSymbol but not PatcherSymbol)
        patcher_getter_ids = {id(getter) for _, _, getter in all_patcher_symbols}
        pure_mergers = [
            (elected_symbol, getter_index, getter)
            for elected_symbol, getter_index, getter in all_merger_symbols
            if id(getter) not in patcher_getter_ids
        ]

        # Find semigroups (both MergerSymbol and PatcherSymbol)
        semigroups = [
            (elected_symbol, getter_index, getter)
            for elected_symbol, getter_index, getter in all_merger_symbols
            if isinstance(getter, SemigroupSymbol)
        ]

        match pure_mergers:
            case [(elected_symbol, getter_index, _)]:
                return ElectedMerger(
                    symbol=elected_symbol, evaluator_getter_index=getter_index
                )
            case []:
                match semigroups:
                    case [(elected_symbol, getter_index, _), *_]:
                        return ElectedMerger(
                            symbol=elected_symbol,
                            evaluator_getter_index=getter_index,
                        )
                    case []:
                        if all_patcher_symbols:
                            return MergerElectionSentinel.PATCHER_ONLY
                        # Note: has_scope_symbol case is no longer needed because
                        # Scope doesn't have evaluated property, so this code path
                        # is only reached for Resource symbols.
                        raise NotImplementedError("No merger definition provided")
            case _:
                raise ValueError("Multiple pure merger definitions found")

    @cached_property
    def lexical_outer(self) -> Mapping["MixinSymbol", Collection[MixinSymbol]]:
        result = defaultdict(set)
        for super_symbol in self._generate_super_references():
            for union in super_symbol.unions:
                result[union].add(super_symbol.outer)
        return result

    @cached_property
    def unions(self):
        return frozenset(self._generate_unions())

    def _generate_unions(self) -> Iterator["MixinSymbol"]:
        yield self
        match self.origin:
            case Nested(outer=outer, key=key):
                for outer_union in outer.super_unions:
                    if outer_union.has_own_key(key):
                        yield outer_union[key]

    def _generate_super_unions(self):
        for super_symbol in self._generate_super_references():
            yield from super_symbol.unions

    def _generate_super_references(self):
        yield self
        yield from self.strict_super_references

    @cached_property
    def super_unions(self):
        return frozenset(self._generate_super_unions())

    def _generate_strict_supers(self) -> Iterator["MixinSymbol"]:
        if self.outer is not OuterSentinel.ROOT:
            for union in self.unions:
                for resolved_reference in union.resolved_bases:
                    for symbol in resolved_reference.get_symbols(self.outer):
                        yield symbol
                        yield from symbol.strict_super_references

    @cached_property
    def strict_super_references(self) -> Collection["MixinSymbol"]:
        return frozenset(self._generate_strict_supers())


class OuterSentinel(Enum):
    """Sentinel value for symbols that have no outer scope (root symbols)."""

    ROOT = auto()


# V1 Runtime classes (Node, Mixin, Scope, Resource) removed - replaced by Mixin/Scope


class MergerElectionSentinel(Enum):
    """Sentinel value for merger election."""

    PATCHER_ONLY = auto()
    """
    Indicates that the symbol has patchers but no merger.
    """


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class ElectedMerger:
    """Represents the elected MergerSymbol's location."""

    symbol: "MixinSymbol"
    """The MixinSymbol that contains the elected merger."""

    evaluator_getter_index: int
    """Index in the MixinSymbol's evaluator_symbols tuple."""


class KeySentinel(Enum):
    """Sentinel value for symbols that have no key (root symbols)."""

    ROOT = auto()


@dataclass(kw_only=True, frozen=True, eq=False)
class EvaluatorSymbol(Symbol):
    """
    Base class for objects that produce Evaluator.
    Held by MixinSymbol via composition (evaluator_symbols cached_property).
    """

    symbol: "MixinSymbol"
    """The MixinSymbol that owns this EvaluatorSymbol."""

    # V1 bind() method removed - use bind() instead

    @abstractmethod
    def bind(self, mixin: "runtime.Mixin") -> "runtime.Evaluator":
        """Create an Evaluator instance for the given Mixin."""
        ...

    @abstractmethod
    def get_same_scope_dependencies(self) -> "Sequence[MixinSymbol]":
        """
        Get MixinSymbols that this evaluator depends on from the same scope (de_bruijn_index=0).

        Concrete subclasses implement this by accessing self.definition.function
        and analyzing its parameters. Only returns same-scope (de_bruijn_index=0) dependencies.
        """
        ...


@dataclass(kw_only=True, frozen=True, eq=False)
class MergerSymbol(EvaluatorSymbol, Generic[TPatch_contra, TResult_co]):
    """
    EvaluatorSymbol that produces Merger.

    Use ``isinstance(getter, MergerSymbol)`` to check if a getter returns a Merger.

    Type Parameters
    ===============

    - ``TPatch_contra``: The type of patches this Merger accepts (contravariant)
    - ``TResult_co``: The type of result this Merger produces (covariant)
    """


@dataclass(kw_only=True, frozen=True, eq=False)
class PatcherSymbol(EvaluatorSymbol, Generic[TPatch_co]):
    """
    EvaluatorSymbol that produces Patcher.

    Use ``isinstance(getter, PatcherSymbol)`` to check if a getter returns a Patcher.

    Type Parameters
    ===============

    - ``TPatch_co``: The type of patches this Patcher produces (covariant)
    """


TResult = TypeVar("TResult")


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class FunctionalMergerSymbol(
    MergerSymbol[TPatch_contra, TResult_co],
    Generic[TPatch_contra, TResult_co],
):
    """EvaluatorSymbol for FunctionalMergerDefinition."""

    definition: "FunctionalMergerDefinition[TPatch_contra, TResult_co]"
    """The definition that created this EvaluatorSymbol."""

    # V1 compiled_function and bind() removed - use compiled_function and bind()

    @cached_property
    def compiled_function(
        self,
    ) -> "Callable[[runtime.Mixin], Callable[[Iterator[TPatch_contra]], TResult_co]]":
        """Compiled function for V2 that takes Mixin and returns the aggregation function."""
        key = self.symbol.key
        assert isinstance(key, str), f"Merger key must be a string, got {type(key)}"
        match self.symbol.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have compiled functions")
            case MixinSymbol() as outer_symbol:
                return _compile_function_with_mixin(
                    outer_symbol, self.definition.function, key
                )

    def bind(
        self, mixin: "runtime.Mixin"
    ) -> "runtime.FunctionalMerger[TPatch_contra, TResult_co]":
        return runtime.FunctionalMerger(evaluator_getter=self, mixin=mixin)

    def get_same_scope_dependencies(self) -> "Sequence[MixinSymbol]":
        return _get_same_scope_dependencies_from_function(
            function=self.definition.function,
            symbol=self.symbol,
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class EndofunctionMergerSymbol(
    MergerSymbol["Endofunction[TResult]", TResult],
    Generic[TResult],
):
    """EvaluatorSymbol for EndofunctionMergerDefinition.

    Returns ``Merger[Endofunction[T], T]`` which accepts endofunction patches.
    """

    definition: "EndofunctionMergerDefinition[TResult]"
    """The definition that created this EvaluatorSymbol."""

    # V1 compiled_function and bind() removed - use compiled_function and bind()

    @cached_property
    def compiled_function(self) -> "Callable[[runtime.Mixin], TResult]":
        """Compiled function for V2 that takes Mixin and returns the base value."""
        key = self.symbol.key
        assert isinstance(key, str), f"Resource key must be a string, got {type(key)}"
        match self.symbol.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have compiled functions")
            case MixinSymbol() as outer_scope:
                return _compile_function_with_mixin(
                    outer_scope,
                    self.definition.function,
                    key,
                )

    def bind(self, mixin: "runtime.Mixin") -> "runtime.EndofunctionMerger[TResult]":
        return runtime.EndofunctionMerger(evaluator_getter=self, mixin=mixin)

    def get_same_scope_dependencies(self) -> "Sequence[MixinSymbol]":
        return _get_same_scope_dependencies_from_function(
            function=self.definition.function,
            symbol=self.symbol,
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class SinglePatcherSymbol(PatcherSymbol[TPatch_co], Generic[TPatch_co]):
    """EvaluatorSymbol for SinglePatcherDefinition."""

    definition: "SinglePatcherDefinition[TPatch_co]"
    """The definition that created this EvaluatorSymbol."""

    # V1 compiled_function and bind() removed - use compiled_function and bind()

    @cached_property
    def compiled_function(self) -> "Callable[[runtime.Mixin], TPatch_co]":
        """Compiled function for V2 that takes Mixin and returns the patch value."""
        key = self.symbol.key
        assert isinstance(key, str), f"Patch key must be a string, got {type(key)}"
        match self.symbol.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have compiled functions")
            case MixinSymbol() as outer_scope:
                return _compile_function_with_mixin(
                    outer_scope,
                    self.definition.function,
                    key,
                )

    def bind(self, mixin: "runtime.Mixin") -> "runtime.SinglePatcher[TPatch_co]":
        return runtime.SinglePatcher(evaluator_getter=self, mixin=mixin)

    def get_same_scope_dependencies(self) -> "Sequence[MixinSymbol]":
        return _get_same_scope_dependencies_from_function(
            function=self.definition.function,
            symbol=self.symbol,
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class MultiplePatcherSymbol(PatcherSymbol[TPatch_co], Generic[TPatch_co]):
    """EvaluatorSymbol for MultiplePatcherDefinition."""

    definition: "MultiplePatcherDefinition[TPatch_co]"
    """The definition that created this EvaluatorSymbol."""

    # V1 compiled_function and bind() removed - use compiled_function and bind()

    @cached_property
    def compiled_function(self) -> "Callable[[runtime.Mixin], Iterable[TPatch_co]]":
        """Compiled function for V2 that takes Mixin and returns the patch values."""
        key = self.symbol.key
        assert isinstance(key, str), f"Patch key must be a string, got {type(key)}"
        match self.symbol.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have compiled functions")
            case MixinSymbol() as outer_symbol:
                return _compile_function_with_mixin(
                    outer_symbol,
                    self.definition.function,
                    key,
                )

    def bind(self, mixin: "runtime.Mixin") -> "runtime.MultiplePatcher[TPatch_co]":
        return runtime.MultiplePatcher(evaluator_getter=self, mixin=mixin)

    def get_same_scope_dependencies(self) -> "Sequence[MixinSymbol]":
        return _get_same_scope_dependencies_from_function(
            function=self.definition.function,
            symbol=self.symbol,
        )


class SemigroupSymbol(MergerSymbol[T, T], PatcherSymbol[T], Generic[T]):
    """
    Marker class for EvaluatorSymbol that is both MergerSymbol and PatcherSymbol.

    Use ``isinstance(getter, SemigroupSymbol)`` to check if an EvaluatorSymbol
    produces a Semigroup (both Merger and Patcher).
    """


# V1 Evaluator runtime classes (Evaluator, Merger, Patcher, FunctionalMerger,
# EndofunctionMerger, SinglePatcher, MultiplePatcher) removed - replaced by V2


@dataclass(kw_only=True, frozen=True, eq=False)
class Definition(ABC):
    """Base class for all definitions."""

    bases: tuple["ResourceReference", ...]
    is_public: bool


@dataclass(kw_only=True, frozen=True, eq=False)
class EvaluatorDefinition(Definition, ABC):
    """
    Base class for definitions that produce EvaluatorSymbols.

    All concrete subclasses must have a ``function`` field of type ``Callable[..., T]``.
    """

    @abstractmethod
    def compile(self, symbol: "MixinSymbol", /) -> "EvaluatorSymbol":
        """
        Compile this definition into an EvaluatorSymbol.

        Called lazily by MixinSymbol.evaluator_symbols cached_property.

        :param symbol: The MixinSymbol that owns this definition.
        :return: An EvaluatorSymbol instance.
        """
        ...


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class MergerDefinition(EvaluatorDefinition, Generic[TPatch_contra, TResult_co]):
    is_eager: bool


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class PatcherDefinition(EvaluatorDefinition, Generic[TPatch_co]):
    pass


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FunctionalMergerDefinition(MergerDefinition[TPatch_contra, TResult_co]):
    """Definition for merge decorator."""

    function: Callable[..., Callable[[Iterator[TPatch_contra]], TResult_co]]

    def compile(
        self, symbol: "MixinSymbol", /
    ) -> "FunctionalMergerSymbol[TPatch_contra, TResult_co]":
        return FunctionalMergerSymbol(symbol=symbol, definition=self)


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class EndofunctionMergerDefinition(
    Generic[TResult], MergerDefinition[Callable[[TResult], TResult], TResult]
):
    """Definition for resource decorator."""

    function: Callable[..., TResult]

    def compile(self, symbol: "MixinSymbol", /) -> "EndofunctionMergerSymbol[TResult]":
        return EndofunctionMergerSymbol(symbol=symbol, definition=self)


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class SinglePatcherDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patch decorator (single patch)."""

    function: Callable[..., TPatch_co]

    def compile(self, symbol: "MixinSymbol", /) -> "SinglePatcherSymbol[TPatch_co]":
        return SinglePatcherSymbol(symbol=symbol, definition=self)


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class MultiplePatcherDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patches decorator (multiple patches)."""

    function: Callable[..., Iterable[TPatch_co]]

    def compile(self, symbol: "MixinSymbol", /) -> "MultiplePatcherSymbol[TPatch_co]":
        return MultiplePatcherSymbol(symbol=symbol, definition=self)


# V1 Semigroup, StaticScope, InstanceScope classes removed - replaced by V2


TSymbol = TypeVar("TSymbol", bound=MixinSymbol)


@dataclass(kw_only=True, frozen=True, eq=False)
class ScopeDefinition(
    Mapping[Hashable, Sequence[Definition]],
    Definition,
    ABC,
):
    """Abstract base for scope definitions that create Scope instances.

    Implements ``Mapping[Hashable, Sequence[Definition]]`` where each key maps to a
    sequence of definitions. The data structure supports multiple definitions per key,
    but the current public API (``@scope`` decorator and module-level scopes) only
    returns one definition per key. Future versions may expose APIs for defining
    multiple same-name definitions within a single scope.
    """

    def __len__(self) -> int:
        return sum(1 for _ in self)


@dataclass(kw_only=True, frozen=True, eq=False)
class ObjectScopeDefinition(ScopeDefinition):
    """Scope definition that discovers children via dir()+getattr() on underlying object."""

    underlying: object

    def __iter__(self) -> Iterator[Hashable]:
        for name in dir(self.underlying):
            try:
                val = getattr(self.underlying, name)
            except AttributeError:
                continue
            if isinstance(val, Definition):
                yield name

    def __getitem__(self, key: Hashable) -> Sequence[Definition]:
        """Get Definitions by key name.

        Raises KeyError if the key does not exist or the value is not a Definition.
        """
        try:
            val = getattr(self.underlying, cast(str, key))
        except AttributeError as error:
            raise KeyError(key) from error
        if not isinstance(val, Definition):
            raise KeyError(key)
        return (val,)


@final
@dataclass(kw_only=True, frozen=True, slots=True, weakref_slot=True)
class MappingScopeDefinition(ScopeDefinition):
    """Scope definition backed by an explicit mapping of keys to definitions."""

    underlying: Mapping[Hashable, Definition]

    def __iter__(self) -> Iterator[Hashable]:
        yield from self.underlying

    def __len__(self) -> int:
        return len(self.underlying)

    def __getitem__(self, key: Hashable) -> Sequence[Definition]:
        if key not in self.underlying:
            raise KeyError(key)
        return (self.underlying[key],)


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class PackageScopeDefinition(ObjectScopeDefinition):
    """A definition for packages that discovers submodules and *.mixin.* files via pkgutil."""

    underlying: ModuleType

    @cached_property
    def _mixin_files(self) -> Mapping[str, Path]:
        """Discover *.mixin.yaml/json/toml files in the package directory."""
        result: dict[str, Path] = {}
        package_paths = getattr(self.underlying, "__path__", None)
        if package_paths is None:
            return result

        mixin_extensions = (".mixin.yaml", ".mixin.yml", ".mixin.json", ".mixin.toml")
        for package_path in package_paths:
            package_dir = Path(package_path)
            if not package_dir.is_dir():
                continue
            for file_path in package_dir.iterdir():
                if not file_path.is_file():
                    continue
                name_lower = file_path.name.lower()
                for extension in mixin_extensions:
                    if name_lower.endswith(extension):
                        # Extract stem: foo.mixin.yaml -> foo
                        stem = file_path.name[: -len(extension)]
                        if stem not in result:
                            result[stem] = file_path
                        break
        return result

    @override
    def __iter__(self) -> Iterator[Hashable]:
        yield from super(PackageScopeDefinition, self).__iter__()

        for mod_info in pkgutil.iter_modules(self.underlying.__path__):
            yield mod_info.name

        # Also yield mixin file stems
        yield from self._mixin_files.keys()

    @override
    def __getitem__(self, key: Hashable) -> Sequence[Definition]:
        """Get Definitions by key name, including submodules and mixin files."""
        definitions: list[Definition] = []

        # Try Python module definitions first
        try:
            definitions.extend(super(PackageScopeDefinition, self).__getitem__(key))
        except KeyError:
            pass

        # Try submodule import
        if not definitions:
            full_name = f"{self.underlying.__name__}.{key}"
            try:
                spec = importlib.util.find_spec(full_name)
                if spec is not None:
                    submod = importlib.import_module(full_name)
                    # Submodules inherit is_public from their parent package
                    if hasattr(submod, "__path__"):
                        definitions.append(
                            PackageScopeDefinition(
                                bases=(), is_public=self.is_public, underlying=submod
                            )
                        )
                    else:
                        definitions.append(
                            ObjectScopeDefinition(
                                bases=(), is_public=self.is_public, underlying=submod
                            )
                        )
            except ImportError:
                pass

        # Try mixin file
        assert isinstance(key, str)
        mixin_file = self._mixin_files.get(key)
        if mixin_file is not None:
            definitions.append(
                _MixinFileScopeDefinition(
                    bases=(),
                    is_public=self.is_public,
                    underlying=mixin_file,
                )
            )

        if not definitions:
            raise KeyError(key)

        return tuple(definitions)


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _MixinFileScopeDefinition(ScopeDefinition):
    """Internal scope definition for a parsed mixin file."""

    underlying: Path

    def __iter__(self) -> Iterator[Hashable]:
        yield from self._parsed.keys()

    def __len__(self) -> int:
        return len(self._parsed)

    def __getitem__(self, key: Hashable) -> Sequence[Definition]:
        assert isinstance(key, str)
        parsed = self._parsed
        if key not in parsed:
            raise KeyError(key)
        return parsed[key]

    @cached_property
    def _parsed(self) -> Mapping[str, Sequence["FileMixinDefinition"]]:
        from mixinject.mixin_parser import parse_mixin_file

        return parse_mixin_file(self.underlying)


def scope(c: object) -> ObjectScopeDefinition:
    """
    Decorator that converts a class into a ScopeDefinition.
    Nested classes MUST be decorated with @scope to be included as sub-scopes.

    Example - Using @extend to inherit from another scope::

        @extend(RelativeReference(de_bruijn_index=1, path=("Base",)))
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
                    R(de_bruijn_index=0, path=("Branch1",)),
                    R(de_bruijn_index=0, path=("Branch2",)),
                )
                @scope
                class Combined:
                    pass

            root = evaluate(Root)
            root.Combined.foo  # "foo"
            root.Combined.bar  # "foo_bar"

    """
    return ObjectScopeDefinition(bases=(), is_public=False, underlying=c)


TDefinition = TypeVar("TDefinition", bound=Definition)


def extend(
    *bases: "ResourceReference",
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

            @extend(R(de_bruijn_index=0, path=("Base",)))
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
                R(de_bruijn_index=0, path=("branch1",)),
                R(de_bruijn_index=0, path=("branch2",)),
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


def _parse_package(module: ModuleType) -> ScopeDefinition:
    """
    Parses a module into a ScopeDefinition.

    Only module-level attributes explicitly decorated with @resource, @patch, @patch_many, or @merge are included.
    Nested modules and packages are recursively parsed with lazy loading.

    IMPORTANT: Bare callables (without decorators) are NOT automatically included.
    Users must explicitly mark all injectable definitions with appropriate decorators.

    For packages (modules with __path__), uses pkgutil.iter_modules to discover submodules
    and importlib.import_module to lazily import them when accessed.
    """
    # Modules are private by default; use modules_public=True in evaluate to make public
    if hasattr(module, "__path__"):
        return PackageScopeDefinition(bases=(), is_public=False, underlying=module)
    return ObjectScopeDefinition(bases=(), is_public=False, underlying=module)


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
                R(de_bruijn_index=0, path=("Branch0",)),
                R(de_bruijn_index=0, path=("Branch1",)),
                R(de_bruijn_index=0, path=("Branch2",)),
            )
            @scope
            class Combined:
                pass

        root = evaluate(Root)
        root.Combined.deduplicated_tags  # frozenset(("tag1", "tag2_dependency_value"))

    Note: For combining multiple scopes, use ``@extend`` with ``RelativeReference``.
    See :func:`scope` for examples.
    """
    return FunctionalMergerDefinition(
        bases=(), function=callable, is_eager=False, is_public=False
    )


def patch(
    callable: Callable[..., TPatch_co],
) -> PatcherDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return SinglePatcherDefinition(bases=(), is_public=False, function=callable)


def patch_many(
    callable: Callable[..., Iterable[TPatch_co]],
) -> PatcherDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return MultiplePatcherDefinition(bases=(), is_public=False, function=callable)


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

    return MultiplePatcherDefinition(
        bases=(), is_public=False, function=empty_patches_provider
    )


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
    return EndofunctionMergerDefinition(
        bases=(), function=callable, is_eager=False, is_public=False
    )


TPublicDefinition = TypeVar("TPublicDefinition", bound=Definition)
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


def public(definition: TPublicDefinition) -> TPublicDefinition:
    """
    Decorator to mark a definition as public.

    Public definitions are accessible from child scopes via dependency injection
    and from getattr/getitem access on the scope object.

    Definitions are private by default, meaning they are only accessible as
    dependencies within the same scope. Use @public to expose them externally.

    Example::

        @public
        @resource
        def api_endpoint() -> str:
            return "/api/v1"

        @public
        @scope
        class NestedScope:
            pass

    :param definition: A Definition to mark as public.
    :return: A new Definition with is_public=True.
    """
    return replace(definition, is_public=True)


# V1 function evaluate() removed - use evaluate() from v2.py instead


def _get_param_resolved_reference(
    param_name: str,
    outer_symbol: MixinSymbol,
) -> "ResolvedReference | RelativeReferenceSentinel":
    """
    Get a ResolvedReference to a parameter using lexical scoping (MixinSymbol chain).

    Traverses up the MixinSymbol chain to find the parameter, counting levels.
    Returns a ResolvedReference with pre-resolved symbol path that can be resolved
    from any Mixin bound to outer_symbol, or RelativeReferenceSentinel.NOT_FOUND
    if the parameter is not found.

    :param param_name: The name of the parameter to find.
    :param outer_symbol: The MixinSymbol to start searching from (lexical scope).
    :return: ResolvedReference with pre-resolved symbol describing how to reach the parameter,
             or RelativeReferenceSentinel.NOT_FOUND if not found.
    """
    de_bruijn_index = 0
    current: MixinSymbol = outer_symbol
    while True:
        if param_name in current:
            target_symbol = current[param_name]
            return ResolvedReference(
                de_bruijn_index=de_bruijn_index,
                path=(param_name,),
                target_symbol_bound=target_symbol,
                origin_symbol=outer_symbol,
            )
        match current.outer:
            case OuterSentinel.ROOT:
                return RelativeReferenceSentinel.NOT_FOUND
            case MixinSymbol() as outer_scope:
                de_bruijn_index += 1
                current = outer_scope


# V1 function _compile_function_with_mixin() removed - use _compile_function_with_mixin() instead


def _get_same_scope_dependencies_from_function(
    function: Callable[..., object],
    symbol: "MixinSymbol",
) -> tuple["MixinSymbol", ...]:
    """
    Get MixinSymbols that function depends on from the same scope (de_bruijn_index=0).

    Mirrors _compile_function_with_mixin logic for same-name skip:
    - Normal parameters: search from symbol.outer (containing scope)
    - Same-name parameters (param.name == symbol.key): search from symbol.outer.outer

    Only returns dependencies with effective de_bruijn_index=0 (same scope as symbol).

    :param function: The function whose parameters to analyze.
    :param symbol: The MixinSymbol that owns this function (for same-name skip).
    :return: Tuple of MixinSymbols that are dependencies from the same scope.
    """
    outer = symbol.outer

    # Only process if we have a parent scope (MixinSymbol) to look up dependencies
    if not isinstance(outer, MixinSymbol):
        return ()

    sig = signature(function)
    result: list[MixinSymbol] = []

    for param in sig.parameters.values():
        # Skip positional-only parameters (used for patches)
        if param.kind == param.POSITIONAL_ONLY:
            continue

        # Same-name skip logic (fixture reference semantics)
        # Mirrors _compile_function_with_mixin
        if param.name == symbol.key:
            # Same-name: search from outer.outer, add 1 to de_bruijn_index
            if isinstance(outer.outer, OuterSentinel):
                # Same-name at root level - not a sibling dependency
                continue
            search_symbol = outer.outer
            extra_levels = 1
        else:
            # Normal: search from outer
            search_symbol = outer
            extra_levels = 0

        resolved_reference = _get_param_resolved_reference(
            param.name,
            search_symbol,
        )
        if resolved_reference is RelativeReferenceSentinel.NOT_FOUND:
            continue

        # Effective de_bruijn_index accounts for same-name skip
        effective_levels_up = resolved_reference.de_bruijn_index + extra_levels
        # Only include dependencies with de_bruijn_index=0 (same scope)
        if effective_levels_up == 0:
            symbol_outer = symbol.outer
            assert isinstance(symbol_outer, MixinSymbol)
            (single_symbol,) = resolved_reference.get_symbols(
                current=symbol_outer,
            )
            result.append(single_symbol)

    return tuple(result)


def _compile_function_with_mixin(
    outer_symbol: "MixinSymbol",
    function: Callable[P, T],
    name: str,
) -> "Callable[[runtime.Mixin], T]":
    """
    Compile a function with pre-computed dependency references for V2.

    Similar to _compile_function_with_mixin but works with Mixin.
    Uses get_symbols + find_mixin to navigate the mixin tree to dependencies.

    :param outer_symbol: The MixinSymbol containing the resource (lexical scope).
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

    # The symbol that owns this resource (for origin tracking in ResolvedReference)
    resource_symbol = outer_symbol[name]

    # Pre-compute ResolvedReferences for each dependency (lexical scoping)
    def compute_dependency_reference(
        parameter: Parameter,
    ) -> tuple[str, ResolvedReference, int]:
        if parameter.name == name:
            # Same-name dependency: start search from outer_symbol.outer
            match outer_symbol.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Same-name dependency '{name}' at root level is not allowed"
                    )
                case MixinSymbol() as search_symbol:
                    pass
            resolved_reference_or_sentinel = _get_param_resolved_reference(
                parameter.name,
                search_symbol,
            )
            match resolved_reference_or_sentinel:
                case RelativeReferenceSentinel.NOT_FOUND:
                    raise LookupError(
                        f"Resource '{name}' depends on '{parameter.name}' "
                        f"which does not exist in scope"
                    )
                case ResolvedReference() as resolved_reference:
                    # Mark that we need to go up one extra level in Mixin chain
                    return (parameter.name, resolved_reference, 1)
        else:
            # Normal dependency
            resolved_reference_or_sentinel = _get_param_resolved_reference(
                parameter.name,
                outer_symbol,
            )
            match resolved_reference_or_sentinel:
                case RelativeReferenceSentinel.NOT_FOUND:
                    raise LookupError(
                        f"Resource '{name}' depends on '{parameter.name}' "
                        f"which does not exist in scope"
                    )
                case ResolvedReference() as resolved_reference:
                    return (parameter.name, resolved_reference, 0)

    dependency_references = tuple(
        compute_dependency_reference(parameter) for parameter in keyword_params
    )

    # Return a compiled function that resolves dependencies at runtime (V2)
    def compiled_wrapper(mixin: "runtime.Mixin") -> T:
        resolved_kwargs: dict[str, object] = {}
        for param_name, resolved_reference, extra_levels in dependency_references:
            # Navigate up extra levels via outer chain (for same-name dependencies)
            search_mixin: runtime.Mixin = mixin
            for _ in range(extra_levels):
                outer_mixin = search_mixin.outer
                assert isinstance(outer_mixin, runtime.Mixin)
                search_mixin = outer_mixin
            # Navigate to target via symbol layer + mixin tree
            search_outer = search_mixin.outer
            assert isinstance(search_outer, runtime.Mixin)
            (target_symbol,) = resolved_reference.get_symbols(
                current=search_outer.symbol,
            )
            dependency_mixin = search_mixin.find_mixin(target_symbol)
            resolved_kwargs[param_name] = dependency_mixin.evaluated

        return function(**resolved_kwargs)  # type: ignore

    def compiled_wrapper_v2_with_positional(
        mixin: "runtime.Mixin",
    ) -> Callable[..., T]:
        resolved_kwargs: dict[str, object] = {}
        for param_name, resolved_reference, extra_levels in dependency_references:
            # Navigate up extra levels via outer chain (for same-name dependencies)
            search_mixin: runtime.Mixin = mixin
            for _ in range(extra_levels):
                outer_mixin = search_mixin.outer
                assert isinstance(outer_mixin, runtime.Mixin)
                search_mixin = outer_mixin
            # Navigate to target via symbol layer + mixin tree
            search_outer = search_mixin.outer
            assert isinstance(search_outer, runtime.Mixin)
            (target_symbol,) = resolved_reference.get_symbols(
                current=search_outer.symbol,
            )
            dependency_mixin = search_mixin.find_mixin(target_symbol)
            resolved_kwargs[param_name] = dependency_mixin.evaluated

        def inner(positional_argument: object, /) -> T:
            return function(positional_argument, **resolved_kwargs)  # type: ignore

        return inner

    if has_positional:
        return compiled_wrapper_v2_with_positional  # type: ignore
    else:
        return compiled_wrapper


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class AbsoluteReference:
    """
    An absolute reference to a resource starting from the root scope.
    """

    path: Final[tuple[Hashable, ...]]

    def resolve(self, symbol: MixinSymbol) -> "ResolvedReference":
        """Resolve this absolute reference from the given symbol.

        Computes de_bruijn_index as the depth from symbol.outer to root.
        """
        # Count depth from symbol.outer (consistent with other reference types)
        depth = 0
        current: MixinSymbol = symbol
        match current.outer:
            case OuterSentinel.ROOT:
                de_bruijn_index = 0
            case MixinSymbol() as first_outer:
                current = first_outer
                while True:
                    match current.outer:
                        case OuterSentinel.ROOT:
                            break
                        case MixinSymbol() as outer_symbol:
                            depth += 1
                            current = outer_symbol
                de_bruijn_index = depth

        # Compute origin_symbol: start from symbol.outer
        start_symbol: MixinSymbol = symbol
        match start_symbol.outer:
            case OuterSentinel.ROOT:
                pass
            case MixinSymbol() as outer_symbol:
                start_symbol = outer_symbol
        origin_symbol: MixinSymbol = start_symbol

        # Navigate up de_bruijn_index levels
        for _ in range(de_bruijn_index):
            match start_symbol.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Cannot navigate up {de_bruijn_index} levels: reached root"
                    )
                case MixinSymbol() as outer_symbol:
                    start_symbol = outer_symbol

        # Resolve path to find target_symbol
        current_symbol: MixinSymbol = start_symbol
        for part in self.path:
            child_symbol = current_symbol.get(part)
            if child_symbol is None:
                raise ValueError(
                    f"Cannot navigate path {self.path!r}: "
                    f"'{current_symbol.key}' has no child '{part}'"
                )
            current_symbol = child_symbol

        return ResolvedReference(
            de_bruijn_index=de_bruijn_index,
            path=self.path,
            target_symbol_bound=current_symbol,
            origin_symbol=origin_symbol,
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class RelativeReference:
    """
    A reference to a resource relative to the current lexical scope.

    This is used to refer to resources in outer scopes.
    """

    de_bruijn_index: Final[int]
    """
    Number of levels to go up in the lexical scope.
    """

    path: Final[tuple[Hashable, ...]]

    def resolve(self, symbol: MixinSymbol) -> "ResolvedReference":
        """Resolve this relative reference from the given symbol."""
        # Compute origin_symbol: start from symbol.outer
        start_symbol: MixinSymbol = symbol
        match start_symbol.outer:
            case OuterSentinel.ROOT:
                pass
            case MixinSymbol() as outer_symbol:
                start_symbol = outer_symbol
        origin_symbol: MixinSymbol = start_symbol

        # Navigate up de_bruijn_index levels
        for _ in range(self.de_bruijn_index):
            match start_symbol.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Cannot navigate up {self.de_bruijn_index} levels: reached root"
                    )
                case MixinSymbol() as outer_symbol:
                    start_symbol = outer_symbol

        # Resolve path to find target_symbol
        current_symbol: MixinSymbol = start_symbol
        for part in self.path:
            child_symbol = current_symbol.get(part)
            if child_symbol is None:
                raise ValueError(
                    f"Cannot navigate path {self.path!r}: "
                    f"'{current_symbol.key}' has no child '{part}'"
                )
            current_symbol = child_symbol

        return ResolvedReference(
            de_bruijn_index=self.de_bruijn_index,
            path=self.path,
            target_symbol_bound=current_symbol,
            origin_symbol=origin_symbol,
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class ResolvedReference:
    """
    A reference with pre-resolved target symbol for compile-time type bound checking.

    The path uses Hashable keys for runtime navigation to support merged scopes.
    The target_symbol_bound provides compile-time type bound checking.
    """

    de_bruijn_index: Final[int]
    """Number of levels to go up in the scope chain."""

    path: Final[tuple[Hashable, ...]]
    """Hashable path for runtime navigation (supports merged scopes)."""

    target_symbol_bound: Final["MixinSymbol"]
    """The final resolved MixinSymbol (for compile-time type bound checking)."""

    origin_symbol: Final["MixinSymbol"]
    """The definition-site symbol where de Bruijn navigation starts.

    This is the ``self.outer`` of the symbol that defined this reference
    (recorded during ``resolve``). Used together with the caller's
    ``outer`` chain to find composition-site symbols at each de Bruijn step.

    Navigation: ``origin_symbol``, ``origin_symbol.outer``,
    ``origin_symbol.outer.outer``, ... traces the definition-site chain.
    """

    def get_symbols(
        self,
        current: "MixinSymbol",
    ) -> tuple["MixinSymbol", ...]:
        """Get all target MixinSymbols by navigating de Bruijn levels.

        At each de Bruijn step, collects all symbols from ``current`` and its
        strict supers whose ``.outer`` is or inherits ``definition_site``.
        Then advances ``definition_site`` one level up.

        This naturally handles multi-path inheritance: when composition flattens
        multiple nesting levels, different strict supers may resolve the same
        de Bruijn reference to different targets.

        :param current: Composition-site parent symbol.
        :return: All resolved target symbols (one per inheritance path).
        """
        currents = frozenset((current,))
        definition_site: MixinSymbol = self.origin_symbol

        for _ in range(self.de_bruijn_index):
            currents = frozenset(
                lexical_outer
                for current in currents
                for lexical_outer in current.lexical_outer[definition_site]
            )
            definition_site = definition_site.outer

        results: list[MixinSymbol] = []
        for current in currents:
            navigated = current
            for key in self.path:
                navigated = navigated[key]
            results.append(navigated)
        return tuple(results)


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class LexicalReference:
    """
    A lexical reference following MIXIN spec resolution algorithm.

    This reference type implements **lexical scoping with late-binding**.

    Symbol Level (Static Analysis)
    ==============================

    Resolution starts from ``self.outer`` (not self). This prevents infinite
    recursion when a symbol references its own name. The algorithm traverses up the
    static hierarchy (``outer``, ``outer.outer``, ...) to
    calculate the ``de_bruijn_index`` (number of levels to go up).

    Runtime Level (Late Binding)
    ============================

    The calculated index is resolved at runtime through the ``outer`` chain. This
    provides late-binding semantics: a reference defined in a base scope will resolve
    to the definition in the actual derived scope if it has been overridden.

    Algorithm Steps (at Symbol Layer)
    ---------------------------------

    At each static level (``outer``, ...):
    1. Is path[0] BOTH a property AND the scope's key? → raise ValueError (ambiguous)
    2. Is path[0] a property of that level? → early binding, return full path
    3. Is path[0] == that level's key? → self-reference, return path[1:]
    4. Recurse to static outer

    The returned RelativeReference has:
    - de_bruijn_index: Static levels to go up.
    - path: For property match, returns full path. For self-reference, returns path[1:].
    """

    path: Final[tuple[Hashable, ...]]

    def resolve(self, symbol: MixinSymbol) -> ResolvedReference:
        """Resolve this lexical reference from the given symbol.

        Strict lexical scoping: only search own definitions, not inherited.
        To reference inherited members, use QualifiedThisReference:
        ``["ScopeName", ~, "inherited_member"]``
        """
        if not self.path:
            raise ValueError("LexicalReference path must not be empty")
        first_segment = self.path[0]
        de_bruijn_index = 0
        # Start from symbol.outer (not symbol) so de_bruijn counts from the
        # same starting point that callers provide as current/current_lexical.
        current: MixinSymbol = symbol
        match current.outer:
            case OuterSentinel.ROOT:
                raise LookupError(f"LexicalReference '{first_segment}' not found")
            case MixinSymbol() as first_outer:
                current = first_outer

        while True:
            # Strict lexical scope: only check own definitions
            is_own_property = current.has_own_key(first_segment)

            # Error on is_public=False resources when de_bruijn_index >= 1
            # Private resources are only visible within their own scope
            # Silently skipping would be surprising behavior for users
            if is_own_property and de_bruijn_index >= 1:
                child_symbol = current.get(first_segment)
                if child_symbol is not None and not child_symbol.is_public:
                    raise LookupError(
                        f"Cannot resolve '{first_segment}': resource is not marked "
                        f"as @public and is not accessible from nested scopes"
                    )

            if is_own_property:
                hashable_path = self.path
                break
            # Recurse to outer
            match current.outer:
                case OuterSentinel.ROOT:
                    raise LookupError(f"LexicalReference '{first_segment}' not found")
                case MixinSymbol() as outer_symbol:
                    de_bruijn_index += 1
                    current = outer_symbol

        # Compute origin_symbol: start from symbol.outer
        start_symbol: MixinSymbol = symbol
        match start_symbol.outer:
            case OuterSentinel.ROOT:
                pass
            case MixinSymbol() as outer_symbol:
                start_symbol = outer_symbol
        origin_symbol: MixinSymbol = start_symbol

        # Navigate up de_bruijn_index levels
        for _ in range(de_bruijn_index):
            match start_symbol.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Cannot navigate up {de_bruijn_index} levels: reached root"
                    )
                case MixinSymbol() as outer_symbol:
                    start_symbol = outer_symbol

        # Resolve path to find target_symbol
        current_symbol: MixinSymbol = start_symbol
        for part in hashable_path:
            child_symbol = current_symbol.get(part)
            if child_symbol is None:
                raise ValueError(
                    f"Cannot navigate path {hashable_path!r}: "
                    f"'{current_symbol.key}' has no child '{part}'"
                )
            current_symbol = child_symbol

        return ResolvedReference(
            de_bruijn_index=de_bruijn_index,
            path=hashable_path,
            target_symbol_bound=current_symbol,
            origin_symbol=origin_symbol,
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FixtureReference:
    """
    A pytest-fixture-style reference with same-name skip semantics.

    Resolution searches through self.outer, self.outer.outer, etc. for a symbol
    containing a property with this name.

    Same-name skip semantics: When resolved from a symbol whose key matches this
    name, the first match is skipped. This allows a symbol to reference an outer
    symbol with the same name, similar to pytest fixtures shadowing outer fixtures.

    The returned RelativeReference has:

    - de_bruijn_index: 1 means found in self.outer, 2 means self.outer.outer, etc.
      Note: de_bruijn_index starts at 1 (not 0) because we count iterations.
    - path: Always (name,) - a single-element tuple.

    Examples:
        From symbol "foo" in scope A where A contains "bar"::

            FixtureReference(name="bar"):
            - Level 1 (A = self.outer): "bar" in A? YES
            - → RelativeReference(de_bruijn_index=1, path=("bar",))

        From symbol "foo" in scope A where A["foo"] exists (same-name skip)::

            FixtureReference(name="foo"):
            - Level 1 (A = self.outer): "foo" in A? YES, but self.key == "foo", skip
            - Level 2 (A.outer): "foo" in A.outer? YES (if found)
            - → RelativeReference(de_bruijn_index=2, path=("foo",))
    """

    name: str

    def resolve(self, symbol: MixinSymbol) -> ResolvedReference:
        """Resolve this fixture reference from the given symbol.

        Pytest fixture style: single name, same-name skips first match.
        """
        skip_first = self.name == symbol.key
        de_bruijn_index = 0
        # Start from symbol.outer (same off-by-one fix as LexicalReference)
        current: MixinSymbol = symbol
        match current.outer:
            case OuterSentinel.ROOT:
                raise LookupError(f"FixtureReference '{self.name}' not found")
            case MixinSymbol() as first_outer:
                current = first_outer

        while True:
            # Check if name exists in current
            if self.name in current:
                # Error on is_public=False resources when de_bruijn_index >= 1
                # Private resources are only visible within their own scope
                # Silently skipping would be surprising behavior for users
                child_symbol = current.get(self.name)
                is_private = child_symbol is not None and not child_symbol.is_public
                if is_private and de_bruijn_index >= 1:
                    raise LookupError(
                        f"Cannot resolve '{self.name}': resource is not marked "
                        f"as @public and is not accessible from nested scopes"
                    )

                if skip_first:
                    skip_first = False
                else:
                    hashable_path: tuple[Hashable, ...] = (self.name,)
                    break
            # Recurse to outer
            match current.outer:
                case OuterSentinel.ROOT:
                    raise LookupError(f"FixtureReference '{self.name}' not found")
                case MixinSymbol() as outer_symbol:
                    de_bruijn_index += 1
                    current = outer_symbol

        # Compute origin_symbol: start from symbol.outer
        start_symbol: MixinSymbol = symbol
        match start_symbol.outer:
            case OuterSentinel.ROOT:
                pass
            case MixinSymbol() as outer_symbol:
                start_symbol = outer_symbol
        origin_symbol: MixinSymbol = start_symbol

        # Navigate up de_bruijn_index levels
        for _ in range(de_bruijn_index):
            match start_symbol.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Cannot navigate up {de_bruijn_index} levels: reached root"
                    )
                case MixinSymbol() as outer_symbol:
                    start_symbol = outer_symbol

        # Resolve path to find target_symbol
        current_symbol: MixinSymbol = start_symbol
        for part in hashable_path:
            child_symbol = current_symbol.get(part)
            if child_symbol is None:
                raise ValueError(
                    f"Cannot navigate path {hashable_path!r}: "
                    f"'{current_symbol.key}' has no child '{part}'"
                )
            current_symbol = child_symbol

        return ResolvedReference(
            de_bruijn_index=de_bruijn_index,
            path=hashable_path,
            target_symbol_bound=current_symbol,
            origin_symbol=origin_symbol,
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class QualifiedThisReference:
    """
    A qualified this reference: [SelfName, ~, property, path].

    The second element is null (~ in YAML), distinguishing from regular inheritance.
    This provides late binding by resolving through the dynamic self of the
    enclosing scope named SelfName.

    Semantics: Walk up the symbol table chain to find a scope whose key matches
    self_name, retrieve that scope's dynamic self (fully composed evaluation),
    then navigate the path segments through allProperties.

    This is analogous to Java's Outer.this.property.path.
    """

    self_name: str
    path: Final[tuple[str, ...]]

    def resolve(self, symbol: MixinSymbol) -> ResolvedReference:
        """Resolve this qualified-this reference from the given symbol.

        Walk up to find scope with matching key, then resolve through dynamic self.
        """
        de_bruijn_index = 0
        # Start from symbol.outer (same off-by-one fix)
        current: MixinSymbol = symbol
        match current.outer:
            case OuterSentinel.ROOT:
                raise LookupError(
                    f"QualifiedThisReference: scope '{self.self_name}' not found"
                )
            case MixinSymbol() as first_outer:
                current = first_outer

        while True:
            if current.key == self.self_name:
                # Found the enclosing scope
                # Path will be resolved at runtime through dynamic self
                hashable_path: tuple[Hashable, ...] = self.path
                break
            # Recurse to outer
            match current.outer:
                case OuterSentinel.ROOT:
                    raise LookupError(
                        f"QualifiedThisReference: scope '{self.self_name}' not found"
                    )
                case MixinSymbol() as outer_symbol:
                    de_bruijn_index += 1
                    current = outer_symbol

        # Compute origin_symbol: start from symbol.outer
        start_symbol: MixinSymbol = symbol
        match start_symbol.outer:
            case OuterSentinel.ROOT:
                pass
            case MixinSymbol() as outer_symbol:
                start_symbol = outer_symbol
        origin_symbol: MixinSymbol = start_symbol

        # Navigate up de_bruijn_index levels
        for _ in range(de_bruijn_index):
            match start_symbol.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Cannot navigate up {de_bruijn_index} levels: reached root"
                    )
                case MixinSymbol() as outer_symbol:
                    start_symbol = outer_symbol

        # Resolve path to find target_symbol
        current_symbol: MixinSymbol = start_symbol
        for part in hashable_path:
            child_symbol = current_symbol.get(part)
            if child_symbol is None:
                raise ValueError(
                    f"Cannot navigate path {hashable_path!r}: "
                    f"'{current_symbol.key}' has no child '{part}'"
                )
            current_symbol = child_symbol

        return ResolvedReference(
            de_bruijn_index=de_bruijn_index,
            path=hashable_path,
            target_symbol_bound=current_symbol,
            origin_symbol=origin_symbol,
        )


ResourceReference: TypeAlias = (
    AbsoluteReference
    | RelativeReference
    | LexicalReference
    | FixtureReference
    | QualifiedThisReference
)
"""
A reference to a resource in the lexical scope.

This is a union type of AbsoluteReference, RelativeReference, LexicalReference, and FixtureReference.
"""


def resource_reference_from_pure_path(path: PurePath) -> ResourceReference:
    """
    Parse a PurePath into a ResourceReference[str].

    Raises ValueError if the path is not normalized.
    A normalized path:
    - Has no '.' components (except a single '.' meaning current directory)
    - Has '..' only at the beginning (for relative paths)

    Examples:
        >>> resource_reference_from_pure_path(PurePath("../foo/bar"))
        RelativeReference(de_bruijn_index=1, path=('foo', 'bar'))
        >>> resource_reference_from_pure_path(PurePath("../../config"))
        RelativeReference(de_bruijn_index=2, path=('config',))
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
        return RelativeReference(de_bruijn_index=0, path=())

    de_bruijn_index = 0
    remaining_parts: list[str] = []
    finished_pardir = False

    for part in all_parts:
        if part == os.curdir:
            raise ValueError(f"Path is not normalized: {path}")
        elif part == os.pardir:
            if finished_pardir:
                raise ValueError(f"Path is not normalized: {path}")
            de_bruijn_index += 1
        else:
            finished_pardir = True
            remaining_parts.append(part)

    return RelativeReference(
        de_bruijn_index=de_bruijn_index, path=tuple(remaining_parts)
    )

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
from dataclasses import dataclass, field, make_dataclass, replace
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
    TYPE_CHECKING,
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
    Never,
    ParamSpec,
    Self,
    Sequence,
    TypeAlias,
    TypeVar,
    assert_never,
    cast,
    final,
    overload,
    override,
)

if TYPE_CHECKING:
    from mixinject import v2


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
TEvaluator_co = TypeVar("TEvaluator_co", bound="Evaluator", covariant=True)


class Symbol(ABC):
    pass


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True)
class Nested:
    """Represents a nested symbol that hasn't resolved its definitions yet."""

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

    .. todo:: MixinV2 and ScopeV2 Redesign

       Implement a new ``MixinV2`` and ``ScopeV2`` design to properly support
       ``is_local`` and ``is_eager`` semantics.

       **MixinV2 (Lazy Evaluation Layer)**

       - ``MixinV2`` can be lazily evaluated to produce either a ``Resource`` or a ``ScopeV2``
       - ``MixinV2`` may be a dynamically generated class
       - ``MixinV2`` is NOT frozen (mutable)
       - All lazy evaluation occurs at the ``MixinV2.evaluated`` level

       **ScopeV2 (Frozen Data Container)**

       - ``ScopeV2`` is a frozen, dynamically generated dataclass
       - ``ScopeV2`` does NOT inherit from ``MixinV2``
       - ``ScopeV2`` has NO lazy evaluation capability at the attribute level
       - All attributes are eagerly resolved when the ``ScopeV2`` instance is created

       **Circular Dependencies Between MixinV2 Instances**

       ``MixinV2`` instances under the same ``ScopeV2`` can have circular dependencies.
       This is achieved through a two-phase construction:

       1. First, construct all ``MixinV2`` instances without arguments (empty initialization)
       2. Then, mutually set references by assigning each ``MixinV2`` instance to the
          appropriate attributes of the others

       This pattern requires ``MixinV2`` to be mutable (not frozen), enabling the deferred
       wiring of circular references after initial construction.

       **Key Difference from Current Design**

       The current ``Scope`` implements lazy evaluation at the attribute level (each field
       is lazily evaluated via descriptors). This duplicates the lazy evaluation already
       provided by ``Mixin``'s single-value lazy evaluation, resulting in redundant and
       inelegant design.

       In the new design:

       - Lazy evaluation happens ONLY at the ``MixinV2.evaluated`` boundary
       - ``ScopeV2`` attributes are NOT lazily evaluated
       - This eliminates the redundancy and provides a cleaner separation of concerns
    """

    origin: Nested | Sequence["Definition"]
    """
    Origin of this symbol:
    - For root symbols: Sequence[Definition] (the definitions directly)
    - For nested symbols: Nested(outer, key) (lazy resolution)
    """

    prototype: "MixinSymbol | PrototypeSymbolSentinel" = (
        PrototypeSymbolSentinel.NOT_INSTANCE
    )
    _nested: weakref.WeakValueDictionary[Hashable, "MixinSymbol"] = field(
        default_factory=weakref.WeakValueDictionary
    )

    @property
    def outer(self) -> "MixinSymbol | OuterSentinel":
        """Get the outer symbol, inferred from origin."""
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
        Inherited definitions should be accessed via ``strict_super_indices``.
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
        """
        return tuple(
            self.to_resolved_reference(reference)
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

    def to_resolved_reference(
        self,
        reference: "ResourceReference",
    ) -> "ResolvedReference":
        """
        Convert a ResourceReference to a ResolvedReference for resolution from outer scope.

        The returned ResolvedReference should be resolved from self.outer (not from self).
        Path symbols are pre-resolved at compile-time to avoid runtime Hashable lookups.

        Analogy with file paths:
        - self = current file `/foo/bar/baz`
        - self.outer = PWD `/foo/bar/`
        - AbsoluteReference `/qux` → ResolvedReference `../../qux` (from PWD)

        For RelativeReference: resolve path to MixinSymbol tuple.
        For AbsoluteReference: levels_up = depth(self.outer) = depth(self) - 1.
        For LexicalReference: MIXIN-style lexical search with self-reference support.
        For FixtureReference: pytest-style search, skip if name == self.key.

        :param reference: The reference to convert.
        :return: A ResolvedReference for resolution from self.outer.
        """
        levels_up: int
        hashable_path: tuple[Hashable, ...]

        match reference:
            case RelativeReference(levels_up=rel_levels_up, path=rel_path):
                levels_up = rel_levels_up
                hashable_path = rel_path
            case AbsoluteReference(path=path):
                depth = 0
                current: MixinSymbol = self
                while True:
                    match current.outer:
                        case OuterSentinel.ROOT:
                            break
                        case MixinSymbol() as outer_symbol:
                            depth += 1
                            current = outer_symbol
                levels_up = depth - 1
                hashable_path = path
            case LexicalReference(path=path):
                # MIXIN-style resolution (see lib.nix lookUpVariable):
                # At each level, check in order:
                # 1. Is first_segment a property? → early binding, return full path
                #    (but skip is_local=True when levels_up >= 1)
                # 2. Is first_segment == that level's key? → self-reference, return path[1:]
                # 3. Recurse to outer
                if not path:
                    raise ValueError("LexicalReference path must not be empty")
                first_segment = path[0]
                levels_up = 0
                current: MixinSymbol = self

                while True:
                    match current.outer:
                        case OuterSentinel.ROOT:
                            raise LookupError(
                                f"LexicalReference '{first_segment}' not found"
                            )
                        case MixinSymbol() as outer_symbol:
                            is_property = first_segment in outer_symbol
                            is_self_reference = first_segment == outer_symbol.key

                            # Error on is_local=True resources when levels_up >= 1
                            # Local resources are only visible within their own scope
                            # Silently skipping would be surprising behavior for users
                            if is_property and levels_up >= 1:
                                child_symbol = outer_symbol.get(first_segment)
                                if child_symbol is not None and child_symbol.is_local:
                                    raise LookupError(
                                        f"Cannot resolve '{first_segment}': resource is marked "
                                        f"as @local and is not accessible from nested scopes"
                                    )

                            if is_property and is_self_reference:
                                raise ValueError(
                                    f"Ambiguous LexicalReference: '{first_segment}' is both "
                                    f"a property of scope '{outer_symbol.key}' and the scope's "
                                    f"own key (self-reference). Use explicit path to disambiguate."
                                )
                            if is_property:
                                hashable_path = path
                                break
                            if is_self_reference:
                                # Self-reference: skip first segment, navigate via rest
                                hashable_path = path[1:]
                                break
                            # Recurse to outer
                            levels_up += 1
                            current = outer_symbol
            case FixtureReference(name=name):
                # Pytest fixture style: single name, same-name skips first match
                skip_first = name == self.key
                levels_up = 0
                current: MixinSymbol = self

                while True:
                    match current.outer:
                        case OuterSentinel.ROOT:
                            raise LookupError(f"FixtureReference '{name}' not found")
                        case MixinSymbol() as outer_symbol:
                            levels_up += 1
                            # Check if name exists in outer_symbol
                            if name in outer_symbol:
                                # Error on is_local=True resources when levels_up >= 1
                                # Local resources are only visible within their own scope
                                # Silently skipping would be surprising behavior for users
                                child_symbol = outer_symbol.get(name)
                                is_local = (
                                    child_symbol is not None and child_symbol.is_local
                                )
                                if is_local and levels_up >= 1:
                                    raise LookupError(
                                        f"Cannot resolve '{name}': resource is marked "
                                        f"as @local and is not accessible from nested scopes"
                                    )

                                if skip_first:
                                    skip_first = False
                                else:
                                    hashable_path = (name,)
                                    break
                            current = outer_symbol
            case _ as unreachable:
                assert_never(unreachable)

        # Resolve hashable path to MixinSymbol path at compile-time
        # Navigate to the starting point for path resolution
        start_symbol: MixinSymbol = self
        match start_symbol.outer:
            case OuterSentinel.ROOT:
                pass
            case MixinSymbol() as outer_symbol:
                start_symbol = outer_symbol

        for _ in range(levels_up):
            match start_symbol.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Cannot navigate up {levels_up} levels: reached root"
                    )
                case MixinSymbol() as outer_symbol:
                    start_symbol = outer_symbol

        # Resolve the path to find target_symbol (for compile-time access)
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
            levels_up=levels_up,
            path=hashable_path,
            target_symbol=current_symbol,
        )

    def resolve_relative_reference(
        self,
        reference: "RelativeReference",
        expected_type: type[TSymbol],
    ) -> TSymbol:
        """
        Resolve a RelativeReference to a MixinSymbol using this symbol as starting point.

        - Navigate up ``levels_up`` levels from this symbol via ``.outer``
        - Then navigate down through ``path`` using ``symbol[key]``

        :param reference: The RelativeReference describing the path to the target symbol.
        :param expected_type: The expected type of the resolved symbol.
        :return: The resolved symbol of the expected type.
        :raises ValueError: If navigation goes beyond the root symbol.
        :raises TypeError: If intermediate or final resolved value is not of expected type.
        """
        current: MixinSymbol = self
        for level in range(reference.levels_up):
            match current.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Cannot navigate up {reference.levels_up} levels: "
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

        # Keys from bases
        for base in cast(Iterator["MixinSymbol"], self.generate_strict_super()):
            for key in base:
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
        if not issubclass(self.mixin_type, Scope):
            raise KeyError(key)

        # Use Nested to create child symbol with lazy definition resolution
        compiled_symbol = MixinSymbol(origin=Nested(outer=self, key=key))

        # If definitions is empty and no bases from super, key doesn't exist
        if not compiled_symbol.definitions and not compiled_symbol.strict_super_indices:
            raise KeyError(key)

        self._nested[key] = compiled_symbol
        return compiled_symbol

    @cached_property
    def instance(self) -> "MixinSymbol | InstanceSymbolSentinel":
        """Get or create the instance symbol for this symbol.

        Returns InstanceSymbolSentinel.ALREADY_INSTANCE if this is already an instance symbol.
        """
        match self.prototype:
            case PrototypeSymbolSentinel.NOT_INSTANCE:
                return replace(self, prototype=self)
            case MixinSymbol():
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
            case MixinSymbol() as outer_symbol:
                return outer_symbol.depth + 1

    @cached_property
    def is_local(self):
        return any(
            definition.is_local
            for super_symbol in chain((self,), self.strict_super_indices)
            for definition in super_symbol.definitions
            if isinstance(definition, MergerDefinition)
        )

    @cached_property
    def is_eager(self):
        return any(
            definition.is_eager
            for super_symbol in chain((self,), self.strict_super_indices)
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
            for symbol in chain((self,), self.strict_super_indices)
            for definition in symbol.definitions
        )
        if not all_definitions:
            return False
        return all(
            isinstance(definition, ScopeDefinition) for definition in all_definitions
        )

    @cached_property
    def mixin_type(self) -> type["Mixin"]:
        """
        Return the Mixin subclass to use for this symbol.

        - If all definitions (own and super) are ScopeDefinition, return a dynamic Scope subclass
        - If no definitions are ScopeDefinition, return Resource
        - If mixed, raise ValueError

        For Scope symbols, generates a dynamic class with:
        - Child MixinSymbol instances as class attributes (descriptors)
        - Custom __dir__ method listing all keys
        """
        all_definitions = tuple(
            definition
            for symbol in chain((self,), self.strict_super_indices)
            for definition in symbol.definitions
        )

        assert all_definitions, f"No definitions found for {self.key}"

        scope_count = sum(
            1
            for definition in all_definitions
            if isinstance(definition, ScopeDefinition)
        )

        if scope_count == 0:
            return Resource

        if scope_count != len(all_definitions):
            raise ValueError(
                f"Mixed ScopeDefinition and non-ScopeDefinition in {self.key}: "
                f"{scope_count} ScopeDefinition, {len(all_definitions) - scope_count} non-ScopeDefinition"
            )

        # Create dynamic Scope subclass with MixinSymbol descriptors
        if self.prototype is PrototypeSymbolSentinel.NOT_INSTANCE:
            base_class: type[Scope] = StaticScope
        else:
            base_class = InstanceScope

        # Create child MixinSymbol instances as class attributes (lazy via Nested)
        child_symbols: dict[str, MixinSymbol] = {
            key: MixinSymbol(origin=Nested(outer=self, key=key))
            for key in self
            if isinstance(key, str) and key.isidentifier()
        }

        # Create cache fields for each child symbol's attribute_name
        cache_fields = tuple(
            (symbol.attribute_name, object, field(init=False))
            for symbol in child_symbols.values()
        )

        def scope_dir(scope_self: Scope) -> Sequence[str]:
            symbol = scope_self.symbol
            symbol_keys = set(key for key in symbol if isinstance(key, str))
            base_keys = set(object.__dir__(scope_self))
            return tuple(symbol_keys | base_keys)

        dynamic_class = make_dataclass(
            f"{base_class.__name__}[{self.key!r}]",
            cache_fields,
            bases=(base_class,),
            slots=True,
            weakref_slot=True,
            namespace={"__dir__": scope_dir, **child_symbols},
        )
        dynamic_class.__final__ = True  # type: ignore[attr-defined]
        return cast(type["Mixin"], dynamic_class)

    def get_mixin(self, outer: "Scope") -> "Mixin":
        """Get cached Mixin for this symbol from outer scope.

        Creates and caches the Mixin object (unevaluated).
        For Resource mixins, call .evaluated to get the evaluated value.
        """
        attribute_name = self.attribute_name
        try:
            return getattr(outer, attribute_name)
        except AttributeError:
            pass
        mixin = self.mixin_type(
            outer=outer, symbol=self, lexical_outer_index=SymbolIndexSentinel.OWN
        )
        setattr(outer, attribute_name, mixin)
        return mixin

    @overload
    def __get__(self, instance: None, owner: type) -> "MixinSymbol": ...

    @overload
    def __get__(self, instance: object, owner: type) -> "MixinSymbol": ...

    def __get__(  # type: ignore[misc]
        self, instance: object, owner: type
    ) -> "Scope | object | MixinSymbol":
        """Descriptor protocol for accessing nested symbols as attributes.

        This method is invoked when MixinSymbol is used as a class attribute
        on dynamically generated Scope subclasses.

        Returns evaluated value for Resources, Scope for Scopes.
        """
        if instance is None or not isinstance(instance, Scope):
            return self

        mixin = self.get_mixin(outer=instance)
        if isinstance(mixin, Resource):
            return mixin.evaluated
        return mixin

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

        def generate_self_and_bases():
            yield (SymbolIndexSentinel.OWN, self)
            yield from enumerate(self.strict_super_indices)

        self_and_bases = tuple(generate_self_and_bases())

        # Collect all (symbol_index, evaluator_getter_index, getter) tuples
        all_merger_symbols: list[
            tuple[SymbolIndexSentinel | int, int, "MergerSymbol"]
        ] = []
        all_patcher_symbols: list[
            tuple[SymbolIndexSentinel | int, int, "PatcherSymbol"]
        ] = []

        for symbol_index, symbol in self_and_bases:
            for getter_index, getter in enumerate(symbol.evaluator_symbols):
                if isinstance(getter, MergerSymbol):
                    all_merger_symbols.append((symbol_index, getter_index, getter))
                if isinstance(getter, PatcherSymbol):
                    all_patcher_symbols.append((symbol_index, getter_index, getter))

        # Check for scope symbols (definitions containing ScopeDefinition)
        has_scope_symbol = any(
            any(isinstance(d, ScopeDefinition) for d in symbol.definitions)
            for _, symbol in self_and_bases
        )

        # Rule 0: Scope MixinSymbol cannot coexist with MergerSymbol/PatcherSymbol
        if has_scope_symbol and (all_merger_symbols or all_patcher_symbols):
            raise ValueError(
                "Scope MixinSymbol cannot coexist with MergerSymbol or PatcherSymbol"
            )

        # Find pure mergers (MergerSymbol but not PatcherSymbol)
        patcher_getter_ids = {id(getter) for _, _, getter in all_patcher_symbols}
        pure_mergers = [
            (symbol_index, getter_index, getter)
            for symbol_index, getter_index, getter in all_merger_symbols
            if id(getter) not in patcher_getter_ids
        ]

        # Find semigroups (both MergerSymbol and PatcherSymbol)
        semigroups = [
            (symbol_index, getter_index, getter)
            for symbol_index, getter_index, getter in all_merger_symbols
            if isinstance(getter, SemigroupSymbol)
        ]

        match pure_mergers:
            case [(symbol_index, getter_index, _)]:
                return ElectedMerger(
                    symbol_index=symbol_index, evaluator_getter_index=getter_index
                )
            case []:
                match semigroups:
                    case [(symbol_index, getter_index, _), *_]:
                        return ElectedMerger(
                            symbol_index=symbol_index,
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
    def union_indices(self) -> Mapping["MixinSymbol", int]:
        """Collect base_indices from outer's strict super symbols."""
        match (self.outer, self.key):
            case (MixinSymbol() as outer_scope, key) if not isinstance(
                key, KeySentinel
            ):
                return _collect_union_indices(outer_scope, key)
            case _:
                return {}

    @final
    @cached_property
    def direct_base_indices(
        self,
    ) -> dict["MixinSymbol", NestedSymbolIndex]:
        # Only symbols with definitions have bases to resolve
        if not self.definitions:
            return {}
        match self.outer:
            case MixinSymbol():
                return {
                    resolved_reference.target_symbol: NestedSymbolIndex(
                        primary_index=OwnBaseIndex(index=own_base_index),
                        secondary_index=SymbolIndexSentinel.OWN,
                    )
                    for own_base_index, resolved_reference in enumerate(
                        self.resolved_bases
                    )
                    if resolved_reference.target_symbol.definitions
                }
            case _:
                return {}

    @final
    @cached_property
    def transitive_base_indices(
        self,
    ) -> dict["MixinSymbol", NestedSymbolIndex]:
        # Only symbols with definitions have bases to resolve
        if not self.definitions:
            return {}
        match self.outer:
            case MixinSymbol():
                return {
                    symbol: (
                        NestedSymbolIndex(
                            primary_index=OwnBaseIndex(index=own_base_index),
                            secondary_index=secondary_index,
                        )
                    )
                    for own_base_index, resolved_reference in enumerate(
                        self.resolved_bases
                    )
                    # Linearized strict super symbols of the extend reference
                    for secondary_index, symbol in enumerate(
                        resolved_reference.target_symbol.generate_strict_super()
                    )
                    if symbol.definitions  # Only include symbols with definitions
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

        .. note::

            Symbols without definitions (inherited-only) are excluded via
            ``if symbol.definitions`` checks in the underlying index mappings.
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
            if symbol.definitions  # Only include symbols with definitions
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
            if symbol.definitions  # Only include symbols with definitions
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


class OuterSentinel(Enum):
    """Sentinel value for symbols that have no outer scope (root symbols)."""

    ROOT = auto()


class Node(ABC):
    """
    Base class for runtime objects in the dependency injection graph.

    - Mixin: Merged result (scope or resource)
    - Evaluator: Transformation that composes a resource (merger or patcher)
    """

    pass


@dataclass(kw_only=True, eq=False)
class Mixin(Node, ABC):
    """Base class for runtime objects that represent merged results.

    Mixin is the base class for both Scope (containers) and Resource (leaf values).

    Note: This class uses ``frozen=False`` as an exception to CONTRIBUTING.md rules.
    Dynamic subclasses use slots fields as cache (set via ``setattr`` after construction).
    Non-cache fields use ``Final`` type hints to indicate immutability at the type level.
    See CONTRIBUTING.md "Exception: frozen=False with Cache Slots" for details.
    """

    symbol: Final["MixinSymbol"]

    outer: Final["Mixin | OuterSentinel"]
    """The outer Mixin or OuterSentinel.ROOT if this is a root Mixin."""

    lexical_outer_index: Final["SymbolIndexSentinel | int"]
    """
    Index to locate the lexical outer scope for dependency resolution.

    - ``SymbolIndexSentinel.OWN``: lexical outer = ``outer``
    - ``int``: lexical outer = ``outer.strict_super_mixins[index]``
    """

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other: object) -> bool:
        return self is other

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

    @cached_property
    def strict_super_mixins(self) -> Sequence["Mixin"]:
        """Get the strict super mixins for this mixin."""
        return tuple(self.generate_strict_super_mixins())

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
                    child_symbol = base_mixin.symbol[self.symbol.key]
                    direct_mixin = child_symbol.mixin_type(
                        symbol=child_symbol,
                        outer=self.outer,
                        lexical_outer_index=i,
                    )
                case OwnBaseIndex(index=i):
                    assert (
                        self.symbol.definitions
                    )  # Must have definitions to have own bases
                    resolved_reference = self.symbol.resolved_bases[i]
                    _logger.debug(
                        "generate_strict_super_mixins: OwnBaseIndex i=%(i)s resolved_reference=%(resolved_reference)s",
                        {"i": i, "resolved_reference": resolved_reference},
                    )
                    resolved_value = resolved_reference.get_mixin(
                        outer=self,
                        lexical_outer_index=self.lexical_outer_index,
                    )
                    # In inheritance context, resolved value must be a Mixin (not evaluated Resource)
                    assert isinstance(resolved_value, Mixin)
                    direct_mixin = resolved_value
                case SymbolIndexSentinel.OWN:
                    direct_mixin = self
            _logger.debug(
                "generate_strict_super_mixins: direct_mixin_key=%(key)s direct_mixin_type=%(type)s",
                {"key": direct_mixin.symbol.key, "type": type(direct_mixin).__name__},
            )
            yield direct_mixin.get_super(nested_index.secondary_index)


@dataclass(kw_only=True, eq=False)
class Scope(Mixin, ABC):
    """
    Base class for scope mixins that contain nested resources.

    Scopes can contain both nested scopes and resources.
    Attribute access is handled by MixinSymbol descriptors.

    Note: This class uses ``frozen=False`` as an exception to CONTRIBUTING.md rules.
    See Mixin docstring and CONTRIBUTING.md for details.
    """

    def __call__(self, **kwargs: object) -> "InstanceScope":
        """
        Create an instance scope with the provided kwargs.

        Creates a new InstanceScope with the same symbol but with kwargs bound.
        When child resources are accessed, kwargs take precedence over symbol lookups.
        """
        instance_symbol = self.symbol.instance
        if instance_symbol is InstanceSymbolSentinel.ALREADY_INSTANCE:
            raise TypeError("Cannot create instance from an instance scope")
        else:
            instance_type = instance_symbol.mixin_type
            assert issubclass(instance_type, InstanceScope)
            return instance_type(
                symbol=self.symbol,
                outer=self.outer,
                lexical_outer_index=self.lexical_outer_index,
                kwargs=kwargs,
            )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class Resource(Mixin):
    """
    Mixin for non-scope resources (leaf nodes in dependency graph).

    Unlike Scope, Resource does not implement Mapping and cannot have children.
    Contains the `evaluated` property for computing resource values.

    Note: This class uses ``frozen=False`` as an exception to CONTRIBUTING.md rules.
    See Mixin docstring and CONTRIBUTING.md for details.
    """

    @cached_property
    def evaluators(self) -> tuple["Evaluator", ...]:
        """
        Lazily create Evaluators from symbol.evaluator_symbols.

        Calls getter.bind(mixin=self) for each EvaluatorSymbol.
        The Resource is fully created at this point, so Evaluator can safely reference self.
        """
        return tuple(
            getter.bind(mixin=self) for getter in self.symbol.evaluator_symbols
        )

    @cached_property
    def evaluated(self):
        """Evaluate this resource by merging patches."""
        elected = self.symbol.elected_merger_index

        # Collect all patcher patches from all Mixin's evaluators (excluding elected)
        def generate_patcher():
            match elected:
                case ElectedMerger(
                    symbol_index=elected_symbol_index,
                    evaluator_getter_index=elected_getter_index,
                ):
                    # Collect patches from own evaluators
                    if elected_symbol_index == SymbolIndexSentinel.OWN:
                        # Exclude the elected evaluator from own
                        for evaluator_index, evaluator in enumerate(self.evaluators):
                            if evaluator_index != elected_getter_index and isinstance(
                                evaluator, Patcher
                            ):
                                yield from evaluator
                    else:
                        # Elected is from super, collect all from own
                        for evaluator in self.evaluators:
                            if isinstance(evaluator, Patcher):
                                yield from evaluator
                    # Collect patches from super mixins (all must be Resource)
                    for index, super_mixin in enumerate(self.strict_super_mixins):
                        assert isinstance(super_mixin, Resource)
                        if index != elected_symbol_index:
                            for evaluator in super_mixin.evaluators:
                                if isinstance(evaluator, Patcher):
                                    yield from evaluator
                        else:
                            # Exclude the elected evaluator's patcher from super
                            for evaluator_index, evaluator in enumerate(
                                super_mixin.evaluators
                            ):
                                if (
                                    evaluator_index != elected_getter_index
                                    and isinstance(evaluator, Patcher)
                                ):
                                    yield from evaluator
                case MergerElectionSentinel.PATCHER_ONLY:
                    for evaluator in self.evaluators:
                        if isinstance(evaluator, Patcher):
                            yield from evaluator
                    for super_mixin in self.strict_super_mixins:
                        assert isinstance(super_mixin, Resource)
                        for evaluator in super_mixin.evaluators:
                            if isinstance(evaluator, Patcher):
                                yield from evaluator

        def apply_endofunction(accumulator: object, endofunction: object) -> object:
            if not callable(endofunction):
                raise TypeError(
                    f"Patcher must yield callable endofunctions, got {type(endofunction).__name__}"
                )
            return endofunction(accumulator)

        if elected is MergerElectionSentinel.PATCHER_ONLY:
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

        # Get Merger evaluator from elected position
        assert isinstance(elected, ElectedMerger)
        elected_mixin = self.get_super(elected.symbol_index)
        assert isinstance(elected_mixin, Resource)
        merger_evaluator = elected_mixin.evaluators[elected.evaluator_getter_index]
        assert isinstance(merger_evaluator, Merger)
        return merger_evaluator.merge(generate_patcher())


class SymbolIndexSentinel(Enum):
    """Sentinel value for symbol indices indicating the symbol itself (not a base)."""

    OWN = auto()


class MergerElectionSentinel(Enum):
    """Sentinel value for merger election."""

    PATCHER_ONLY = auto()
    """
    Indicates that the symbol has patchers but no merger.
    """


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class ElectedMerger:
    """Represents the position of the elected MergerSymbol."""

    symbol_index: SymbolIndexSentinel | int
    """MixinSymbol index (OWN for self, int for position in strict_super_indices)."""

    evaluator_getter_index: int
    """Index in the MixinSymbol's evaluator_symbols tuple."""


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
    Two-dimensional index of MixinSymbol in outer MixinSymbol, supporting O(1) random access.

    Basic Concept
    =============

    ``NestedSymbolIndex`` uses a two-dimensional index ``(primary_index, secondary_index)`` to locate
    a MixinSymbol's position in its outer MixinSymbol's linearized inheritance chain.

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

    Given ``nested_symbol: MixinSymbol`` with ``key`` in ``outer: MixinSymbol``,
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
        target = _resolve_symbol_reference(extend_refs[i], outer, MixinSymbol)

    - ``NestedSymbolIndex(primary_index=OwnBaseIndex(index=i), secondary_index=j)``::

        # The j-th strict super symbol of extend_refs[i]
        extend_refs = nested_symbol.definition.bases
        own_base = _resolve_symbol_reference(extend_refs[i], outer, MixinSymbol)
        target = tuple(own_base.generate_strict_super())[j]

    JIT Optimization Use Cases
    ===========================

    This data structure is designed for JIT and Proxy optimization:

    1. **Eliminate runtime traversal**: JIT can directly access specific Symbols using indices,
       without traversing ``generate_strict_super()``

    2. **O(1) random access**: Given ``NestedSymbolIndex``, the MixinSymbol's position can be directly
       computed with O(1) time complexity

    3. **Typed indices**: Combined with ``merger_base_indices``, ``patcher_base_indices``,
       ``scope_base_indices``, JIT can directly access specific types of Symbols

    Collaboration with Typed Symbols
    ================================

    After refactoring, this index will be used for the following typed index properties:

    ::

        merger_base_indices: Mapping[MergerSymbol, NestedSymbolIndex]
        patcher_base_indices: Mapping[PatcherSymbol, NestedSymbolIndex]
        scope_base_indices: Mapping[MixinSymbol, NestedSymbolIndex]

    JIT Usage Example::

        # Directly access all Mergers without traversal and isinstance checks
        for merger, index in scope.symbol.merger_base_indices.items():
            evaluator = merger.bind(mixin)  # Return type guaranteed to be Merger
    """

    primary_index: Final[PrimarySymbolIndex]
    secondary_index: Final[SecondarySymbolIndex]


@dataclass(kw_only=True, frozen=True, eq=False)
class EvaluatorSymbol(Symbol, Generic[TEvaluator_co]):
    """
    Base class for objects that produce Evaluators.
    Held by MixinSymbol via composition (evaluator_symbols cached_property).
    """

    symbol: "MixinSymbol"
    """The MixinSymbol that owns this EvaluatorSymbol."""

    @abstractmethod
    def bind(self, mixin: "Mixin") -> TEvaluator_co:
        """Create an Evaluator instance for the given Mixin."""
        ...


@dataclass(kw_only=True, frozen=True, eq=False)
class MergerSymbol(
    EvaluatorSymbol["Merger[TPatch_contra, TResult_co]"],
    Generic[TPatch_contra, TResult_co],
):
    """
    EvaluatorSymbol that produces Merger.

    Use ``isinstance(getter, MergerSymbol)`` to check if a getter returns a Merger.

    Type Parameters
    ===============

    - ``TPatch_contra``: The type of patches this Merger accepts (contravariant)
    - ``TResult_co``: The type of result this Merger produces (covariant)
    """


@dataclass(kw_only=True, frozen=True, eq=False)
class PatcherSymbol(EvaluatorSymbol["Patcher[TPatch_co]"], Generic[TPatch_co]):
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

    @cached_property
    def compiled_function(
        self,
    ) -> Callable[["Mixin"], Callable[[Iterator[TPatch_contra]], TResult_co]]:
        """Compiled function that takes a Mixin and returns the aggregation function."""
        key = self.symbol.key
        assert isinstance(key, str), f"Merger key must be a string, got {type(key)}"
        match self.symbol.outer:
            case OuterSentinel.ROOT:
                raise ValueError("Root symbols do not have compiled functions")
            case MixinSymbol() as outer_symbol:
                return _compile_function_with_mixin(
                    outer_symbol, self.definition.function, key
                )

    def bind(self, mixin: "Mixin") -> "FunctionalMerger[TPatch_contra, TResult_co]":
        return FunctionalMerger(mixin=mixin, evaluator_getter=self)

    def bind_v2(
        self, mixin: "v2.MixinV2"
    ) -> "v2.FunctionalMergerV2[TPatch_contra, TResult_co]":
        return v2.FunctionalMergerV2(
            evaluator_getter=self, mixin=mixin
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

    @cached_property
    def compiled_function(self) -> Callable[["Mixin"], TResult]:
        """Compiled function that takes a Mixin and returns the base value."""
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

    def bind(self, mixin: "Mixin") -> "EndofunctionMerger[TResult]":
        return EndofunctionMerger(mixin=mixin, evaluator_getter=self)

    def bind_v2(
        self, mixin: "v2.MixinV2"
    ) -> "v2.EndofunctionMergerV2[TResult]":
        return v2.EndofunctionMergerV2(
            evaluator_getter=self, mixin=mixin
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class SinglePatcherSymbol(PatcherSymbol[TPatch_co], Generic[TPatch_co]):
    """EvaluatorSymbol for SinglePatcherDefinition."""

    definition: "SinglePatcherDefinition[TPatch_co]"
    """The definition that created this EvaluatorSymbol."""

    @cached_property
    def compiled_function(self) -> Callable[["Mixin"], TPatch_co]:
        """Compiled function that takes a Mixin and returns the patch value."""
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

    def bind(self, mixin: "Mixin") -> "SinglePatcher[TPatch_co]":
        return SinglePatcher(mixin=mixin, evaluator_getter=self)

    def bind_v2(
        self, mixin: "v2.MixinV2"
    ) -> "v2.SinglePatcherV2[TPatch_co]":
        return v2.SinglePatcherV2(
            evaluator_getter=self, mixin=mixin
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class MultiplePatcherSymbol(PatcherSymbol[TPatch_co], Generic[TPatch_co]):
    """EvaluatorSymbol for MultiplePatcherDefinition."""

    definition: "MultiplePatcherDefinition[TPatch_co]"
    """The definition that created this EvaluatorSymbol."""

    @cached_property
    def compiled_function(self) -> Callable[["Mixin"], Iterable[TPatch_co]]:
        """Compiled function that takes a Mixin and returns the patch values."""
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

    def bind(self, mixin: "Mixin") -> "MultiplePatcher[TPatch_co]":
        return MultiplePatcher(mixin=mixin, evaluator_getter=self)

    def bind_v2(
        self, mixin: "v2.MixinV2"
    ) -> "v2.MultiplePatcherV2[TPatch_co]":
        return v2.MultiplePatcherV2(
            evaluator_getter=self, mixin=mixin
        )


class SemigroupSymbol(MergerSymbol[T, T], PatcherSymbol[T], Generic[T]):
    """
    Marker class for EvaluatorSymbol that is both MergerSymbol and PatcherSymbol.

    Use ``isinstance(getter, SemigroupSymbol)`` to check if an EvaluatorSymbol
    produces a Semigroup (both Merger and Patcher).
    """


@dataclass(kw_only=True, frozen=True, eq=False)
class Evaluator(Node):
    """
    Base class for resource evaluators (Merger and Patcher).

    Evaluators are held by Mixin via composition (Mixin.evaluators field).
    """

    mixin: "Mixin"
    """The Mixin that holds this Evaluator."""


class Merger(Evaluator, Generic[TPatch_contra, TResult_co]):
    """Evaluator that merges patches to produce a result."""

    @abstractmethod
    def merge(self, patches: Iterator[TPatch_contra]) -> TResult_co: ...


class Patcher(Evaluator, Iterable[TPatch_co], Generic[TPatch_co]):
    """
    Evaluator that provides patches to be applied to a Merger's result.
    """


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class FunctionalMerger(Merger[TPatch_contra, TResult_co]):
    """Evaluator for FunctionalMergerDefinition."""

    evaluator_getter: "FunctionalMergerSymbol[TPatch_contra, TResult_co]"
    """The EvaluatorSymbol that created this Evaluator."""

    def merge(self, patches: Iterator[TPatch_contra]) -> TResult_co:
        aggregation_function = self.evaluator_getter.compiled_function(self.mixin)
        return aggregation_function(patches)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class EndofunctionMerger(Merger["Endofunction[TResult]", TResult]):
    """Evaluator for EndofunctionMergerDefinition."""

    evaluator_getter: "EndofunctionMergerSymbol[TResult]"
    """The EvaluatorSymbol that created this Evaluator."""

    def merge(self, patches: Iterator["Endofunction[TResult]"]) -> TResult:
        base_value = self.evaluator_getter.compiled_function(self.mixin)
        return reduce(
            lambda accumulator, endofunction: endofunction(accumulator),
            patches,
            base_value,
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class SinglePatcher(Patcher[TPatch_co]):
    """Evaluator for SinglePatcherDefinition."""

    evaluator_getter: "SinglePatcherSymbol[TPatch_co]"
    """The EvaluatorSymbol that created this Evaluator."""

    def __iter__(self) -> Iterator[TPatch_co]:
        yield self.evaluator_getter.compiled_function(self.mixin)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True)
class MultiplePatcher(Patcher[TPatch_co]):
    """Evaluator for MultiplePatcherDefinition."""

    evaluator_getter: "MultiplePatcherSymbol[TPatch_co]"
    """The EvaluatorSymbol that created this Evaluator."""

    def __iter__(self) -> Iterator[TPatch_co]:
        yield from self.evaluator_getter.compiled_function(self.mixin)


def _collect_union_indices(
    outer_symbol: "MixinSymbol", key: Hashable, /
) -> Mapping["MixinSymbol", int]:
    """Collect base_indices from outer_symbol's strict super symbols."""
    return {
        cast("MixinSymbol", item_symbol): index
        for index, base in enumerate(
            cast(Iterator["MixinSymbol"], outer_symbol.generate_strict_super())
        )
        if (item_symbol := base.get(key)) is not None
    }


@dataclass(kw_only=True, frozen=True, eq=False)
class Definition(ABC):
    """Base class for all definitions."""

    bases: tuple["ResourceReference", ...]


@dataclass(kw_only=True, frozen=True, eq=False)
class EvaluatorDefinition(Definition, ABC):
    """Base class for definitions that produce EvaluatorSymbols."""

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
    is_local: bool


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


class Semigroup(Merger[T, T], Patcher[T], Generic[T]):
    pass


@dataclass(kw_only=True, eq=False)
class StaticScope(Scope):
    """
    Scope for static access (no kwargs).

    Used when accessing scopes without instance parameters.
    Base class for dynamically generated scope classes.

    Note: This class uses ``frozen=False`` as an exception to CONTRIBUTING.md rules.
    See Mixin docstring and CONTRIBUTING.md for details.
    """

    pass


@dataclass(kw_only=True, eq=False)
class InstanceScope(Scope):
    """
    Scope for instance access (with kwargs).

    Used when accessing scopes with instance parameters provided via Scope.__call__(**kwargs).
    When child resources are accessed, patcher-only resources use kwargs values as base values.
    Base class for dynamically generated instance scope classes.

    Note: This class uses ``frozen=False`` as an exception to CONTRIBUTING.md rules.
    See Mixin docstring and CONTRIBUTING.md for details.
    """

    kwargs: Final[Mapping[str, object]]


TSymbol = TypeVar("TSymbol", bound=MixinSymbol)


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class ScopeDefinition(
    Mapping[Hashable, Sequence[Definition]],
    Definition,
):
    """Base class for scope definitions that create Scope instances from underlying objects.

    Implements ``Mapping[Hashable, Sequence[Definition]]`` where each key maps to a
    sequence of definitions. The data structure supports multiple definitions per key,
    but the current public API (``@scope`` decorator and module-level scopes) only
    returns one definition per key. Future versions may expose APIs for defining
    multiple same-name definitions within a single scope.
    """

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
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class PackageScopeDefinition(ScopeDefinition):
    """A definition for packages that discovers submodules via pkgutil."""

    underlying: ModuleType

    @override
    def __iter__(self) -> Iterator[Hashable]:
        yield from super(PackageScopeDefinition, self).__iter__()

        for mod_info in pkgutil.iter_modules(self.underlying.__path__):
            yield mod_info.name

    @override
    def __getitem__(self, key: Hashable) -> Sequence[Definition]:
        """Get Definitions by key name, including lazily imported submodules."""
        try:
            return super(PackageScopeDefinition, self).__getitem__(key)
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
            return (PackageScopeDefinition(bases=(), underlying=submod),)
        else:
            return (ScopeDefinition(bases=(), underlying=submod),)


def scope(c: object) -> ScopeDefinition:
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
    return ScopeDefinition(bases=(), underlying=c)


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


def _parse_package(module: ModuleType) -> ScopeDefinition:
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
        return PackageScopeDefinition(bases=(), underlying=module)
    return ScopeDefinition(bases=(), underlying=module)


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
    return FunctionalMergerDefinition(
        bases=(), function=callable, is_eager=False, is_local=False
    )


def patch(
    callable: Callable[..., TPatch_co],
) -> PatcherDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return SinglePatcherDefinition(bases=(), function=callable)


def patch_many(
    callable: Callable[..., Iterable[TPatch_co]],
) -> PatcherDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return MultiplePatcherDefinition(bases=(), function=callable)


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

    return MultiplePatcherDefinition(bases=(), function=empty_patches_provider)


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
        bases=(), function=callable, is_eager=False, is_local=False
    )


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
    *namespaces: ModuleType | ScopeDefinition,
) -> Scope:
    """
    Resolves a Scope from the given objects.

    When multiple namespaces are provided, they are union-mounted at the root level.
    Resources from all namespaces are merged according to the merger election algorithm.

    :param namespaces: Modules or namespace definitions (decorated with @scope) to resolve resources from.
    :return: The root Scope.

    Example::

        root = evaluate(MyNamespace)
        root = evaluate(Base, Override)  # Union mount: Override's definitions take precedence

    """
    assert namespaces, "evaluate() requires at least one namespace"

    def to_scope_definition(
        namespace: ModuleType | ScopeDefinition,
    ) -> ScopeDefinition:
        if isinstance(namespace, ScopeDefinition):
            return namespace
        if isinstance(namespace, ModuleType):
            return _parse_package(namespace)
        assert_never(namespace)

    definitions = tuple(to_scope_definition(namespace) for namespace in namespaces)

    root_symbol = MixinSymbol(origin=definitions)
    root_mixin = root_symbol.mixin_type(
        symbol=root_symbol,
        outer=OuterSentinel.ROOT,
        lexical_outer_index=SymbolIndexSentinel.OWN,
    )
    assert isinstance(root_mixin, Scope), "Root mixin must be a Scope"
    return root_mixin


def _get_param_resolved_reference(
    param_name: str, outer_symbol: MixinSymbol
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
    levels_up = 0
    current: MixinSymbol = outer_symbol
    while True:
        if param_name in current:
            target_symbol = current[param_name]
            return ResolvedReference(
                levels_up=levels_up,
                path=(param_name,),
                target_symbol=target_symbol,
            )
        match current.outer:
            case OuterSentinel.ROOT:
                return RelativeReferenceSentinel.NOT_FOUND
            case MixinSymbol() as outer_scope:
                levels_up += 1
                current = outer_scope


def _compile_function_with_mixin(
    outer_symbol: MixinSymbol,
    function: Callable[P, T],
    name: str,
) -> Callable[[Mixin], T]:
    """
    Compile a function with pre-computed dependency references (lexical scoping).

    Returns a function that takes a Mixin and:
    1. Resolves dependencies using pre-computed RelativeReferences
    2. Calls the original function with resolved dependencies

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

    # Pre-compute ResolvedReferences for each dependency (lexical scoping)
    def compute_dependency_reference(
        parameter: Parameter,
    ) -> tuple[str, ResolvedReference, int]:
        if parameter.name == name:
            # Same-name dependency: start search from outer_symbol.outer (lexical)
            match outer_symbol.outer:
                case OuterSentinel.ROOT:
                    raise ValueError(
                        f"Same-name dependency '{name}' at root level is not allowed"
                    )
                case MixinSymbol() as search_symbol:
                    pass
            resolved_reference_or_sentinel = _get_param_resolved_reference(
                parameter.name, search_symbol
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
                parameter.name, outer_symbol
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

    # Return a compiled function that resolves dependencies at runtime
    def compiled_wrapper(mixin: Mixin) -> T:
        resolved_kwargs: dict[str, object] = {}
        for param_name, resolved_ref, extra_levels in dependency_references:
            # Navigate up extra levels via lexical_outer chain (for same-name dependencies)
            search_mixin: Mixin = mixin
            for _ in range(extra_levels):
                search_mixin = search_mixin.lexical_outer
            # get_mixin returns Mixin; evaluate Resources to get the value
            resolved_mixin = resolved_ref.get_mixin(
                outer=search_mixin,
                lexical_outer_index=search_mixin.lexical_outer_index,
            )
            if isinstance(resolved_mixin, Resource):
                resolved_kwargs[param_name] = resolved_mixin.evaluated
            else:
                resolved_kwargs[param_name] = resolved_mixin

        return function(**resolved_kwargs)  # type: ignore

    def compiled_wrapper_with_positional(mixin: Mixin) -> Callable[..., T]:
        resolved_kwargs: dict[str, object] = {}
        for param_name, resolved_ref, extra_levels in dependency_references:
            # Navigate up extra levels via lexical_outer chain (for same-name dependencies)
            search_mixin: Mixin = mixin
            for _ in range(extra_levels):
                search_mixin = search_mixin.lexical_outer
            # get_mixin returns Mixin; evaluate Resources to get the value
            resolved_mixin = resolved_ref.get_mixin(
                outer=search_mixin,
                lexical_outer_index=search_mixin.lexical_outer_index,
            )
            if isinstance(resolved_mixin, Resource):
                resolved_kwargs[param_name] = resolved_mixin.evaluated
            else:
                resolved_kwargs[param_name] = resolved_mixin

        def inner(positional_arg: object, /) -> T:
            return function(positional_arg, **resolved_kwargs)  # type: ignore

        return inner

    if has_positional:
        return compiled_wrapper_with_positional  # type: ignore
    else:
        return compiled_wrapper


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class AbsoluteReference:
    """
    An absolute reference to a resource starting from the root scope.
    """

    path: Final[tuple[Hashable, ...]]


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class RelativeReference:
    """
    A reference to a resource relative to the current lexical scope.

    This is used to refer to resources in outer scopes.
    """

    levels_up: Final[int]
    """
    Number of levels to go up in the lexical scope.
    """

    path: Final[tuple[Hashable, ...]]


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class ResolvedReference:
    """
    A reference with pre-resolved target symbol for compile-time access.

    The path uses Hashable keys for runtime navigation to support merged scopes.
    The target_symbol provides compile-time access to the resolved symbol.
    """

    levels_up: Final[int]
    """Number of levels to go up in the lexical scope."""

    path: Final[tuple[Hashable, ...]]
    """Hashable path for runtime navigation (supports merged scopes)."""

    target_symbol: Final["MixinSymbol"]
    """The final resolved MixinSymbol (for compile-time access)."""

    def get_mixin(
        self,
        outer: "Mixin",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "Mixin":
        """
        Get the target Mixin by navigating from outer.

        Uses key-based lookup at runtime to support merged scopes correctly.
        Returns the unevaluated Mixin object.

        :param outer: The mixin from which navigation starts.
        :param lexical_outer_index: The lexical outer index of the caller.
        :return: The resolved Mixin (call .evaluated for Resources).
        """
        # Start from outer.outer (the parent scope where we search)
        if isinstance(outer.outer, Mixin):
            current: Mixin | object = outer.outer
        else:
            current = outer  # Root case: stay at outer

        current_lexical_index: SymbolIndexSentinel | int = lexical_outer_index

        for _ in range(self.levels_up):
            assert isinstance(current, Mixin)
            base = current.get_super(current_lexical_index)
            current_lexical_index = base.lexical_outer_index
            assert isinstance(base.outer, Mixin)
            current = base.outer

        # Navigate through path using key-based lookup (supports merged scopes)
        path = self.path
        for index, key in enumerate(path):
            assert isinstance(current, Scope)
            result = current.symbol[key].get_mixin(outer=current)
            if index < len(path) - 1:
                # Intermediate step: must be a Scope to continue navigation
                assert isinstance(result, Scope)
            current = result

        return current

    def get_mixin_v2(
        self,
        outer: "v2.MixinV2",
        lexical_outer_index: "SymbolIndexSentinel | int",
    ) -> "v2.MixinV2":
        """
        Get the target MixinV2 by navigating from outer using V2 semantics.

        Similar to get_mixin but works with V2's frozen ScopeV2.
        Uses key-based lookup at runtime to support merged scopes correctly.

        NOTE: This only handles non-local resources via navigation. Local resources
        at the same scope level are accessed via _sibling_dependencies, not navigation.

        :param outer: The MixinV2 from which navigation starts.
        :param lexical_outer_index: The lexical outer index of the caller.
        :return: The resolved MixinV2 (call .evaluated for actual value).
        """
        # Start from outer.outer (the parent scope where we search)
        if isinstance(outer.outer, v2.MixinV2):
            current: v2.MixinV2 = outer.outer
        else:
            current = outer  # Root case: stay at outer

        current_lexical_index: SymbolIndexSentinel | int = lexical_outer_index

        # Traverse up the lexical scope chain
        for _ in range(self.levels_up):
            base = current.get_super(current_lexical_index)
            current_lexical_index = base.lexical_outer_index  # KEY: Chain the index!
            assert isinstance(base.outer, v2.MixinV2)
            current = base.outer

        # Navigate through path using key-based lookup
        # At this point, current is a MixinV2 that evaluates to a ScopeV2
        for key in self.path:
            scope = current.evaluated
            assert isinstance(scope, v2.ScopeV2), (
                f"Expected ScopeV2 during navigation, got {type(scope).__name__}"
            )

            # Look up child by key in frozen _children
            child_symbol = scope.symbol.get(key)
            if child_symbol is None:
                raise ValueError(
                    f"Key {key!r} not found in scope {scope.symbol.key!r}"
                )
            if child_symbol not in scope._children:
                raise ValueError(
                    f"Key {key!r} not in _children (is it local?)"
                )
            # _children ALWAYS contains MixinV2 (never evaluated values)
            current = scope._children[child_symbol]

        return current


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class LexicalReference:
    """
    A lexical reference following MIXIN spec resolution algorithm.

    Resolution starts from self.outer (not self), so self[path[0]] is never resolved.
    This prevents infinite recursion when a symbol references its own name.

    At each level (self.outer, self.outer.outer, ...), check:

    1. Is path[0] BOTH a property AND the scope's key? → raise ValueError (ambiguous)
    2. Is path[0] a property of that level? → early binding, return full path
    3. Is path[0] == that level's key? → self-reference, return path[1:]
    4. Recurse to outer

    Note: If a scope has a property with the same name as its key, this is ambiguous
    and raises ValueError. This strict behavior preserves future compatibility.

    The returned RelativeReference has:

    - levels_up: 0 means resolve from self.outer, 1 means self.outer.outer, etc.
    - path: For property match, returns full path. For self-reference, returns path[1:].

    Examples:
        From symbol "inner" in scope A where A contains "target"::

            LexicalReference(path=("target",)):
            - Level 0 (A = self.outer): "target" in A? YES
            - → RelativeReference(levels_up=0, path=("target",))

        From symbol "inner" in scope A where A.key == "A"::

            LexicalReference(path=("A", "foo")):
            - Level 0 (A = self.outer): "A" in A? NO, "A" == A.key? YES
            - → RelativeReference(levels_up=0, path=("foo",))  # path[1:], first segment dropped

        From symbol "foo" in scope Container where Container["foo"] exists::

            LexicalReference(path=("foo",)):
            - Level 0 (Container = self.outer): "foo" in Container? YES
            - → RelativeReference(levels_up=0, path=("foo",))
            - Note: self["foo"] would be the symbol itself, but we start from self.outer,
              so Container["foo"] is found (not self).

        Ambiguous case (scope A has A.key == "A" AND A["A"] exists)::

            LexicalReference(path=("A", "bar")):
            - Level 0 (A = self.outer): "A" in A? YES, "A" == A.key? YES
            - → raises ValueError: ambiguous reference
            - Note: Both property and self-reference match. This is disallowed to preserve
              future compatibility for choosing either semantic.
    """

    path: Final[tuple[Hashable, ...]]


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

    - levels_up: 1 means found in self.outer, 2 means self.outer.outer, etc.
      Note: levels_up starts at 1 (not 0) because we count iterations.
    - path: Always (name,) - a single-element tuple.

    Examples:
        From symbol "foo" in scope A where A contains "bar"::

            FixtureReference(name="bar"):
            - Level 1 (A = self.outer): "bar" in A? YES
            - → RelativeReference(levels_up=1, path=("bar",))

        From symbol "foo" in scope A where A["foo"] exists (same-name skip)::

            FixtureReference(name="foo"):
            - Level 1 (A = self.outer): "foo" in A? YES, but self.key == "foo", skip
            - Level 2 (A.outer): "foo" in A.outer? YES (if found)
            - → RelativeReference(levels_up=2, path=("foo",))
    """

    name: str


ResourceReference: TypeAlias = (
    AbsoluteReference | RelativeReference | LexicalReference | FixtureReference
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

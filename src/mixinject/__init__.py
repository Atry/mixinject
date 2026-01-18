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

**Proxy**
    An object that contains resources, accessed via attribute access (``.`` operator).
    Proxies can be nested to form hierarchical structures, analogous to a filesystem directory
    hierarchy. See :class:`Proxy`.

**Lexical Scope**
    The lookup chain for resolving resources, scanning from inner to outer layers.
    See :data:`LexicalScope`.

**Merger**
    An object that creates a resource value by aggregating patches. See :class:`Merger`.

**Patcher**
    An object that provides patches to be applied to a Merger's result. See :class:`Patcher`.

**Semigroup**
    An object that is BOTH Merger AND Patcher simultaneously. This enables commutative
    composition where any item can serve as the merger while others contribute patches.
    Example: :func:`scope` creates a semigroup for nested Proxy composition.

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
    root.ignored_function  # AttributeError: 'CachedProxy' object has no attribute 'ignored_function'

Union Filesystem Analogy
========================

If we make an analogy to union filesystems:

- :class:`Proxy` objects are like directory objects
- Resources are like files
- Modules, packages, callables, and :class:`ScopeDefinition` are filesystem definitions before mounting
- The compiled result (from :func:`mount`) is a concrete :class:`Proxy` that implements resource access

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
| @scope            | Yes      | Yes     | Semigroup for nested Proxy creation      |
+-------------------+----------+---------+------------------------------------------+

.. todo::
    支持 phony 伪目标，用于标记返回 ``None`` 的 Semigroup。

    类似于 Makefile 中的 ``.PHONY`` 目标，phony 资源主要用于触发副作用而非产生值。
    这对于以下场景很有用：

    - 初始化操作（如数据库连接池预热）
    - 资源清理（如关闭文件句柄）
    - 触发多个依赖的聚合操作

    设计考虑：

    1. **声明方式**：新增 ``@phony`` 装饰器，标记返回 ``None`` 的资源定义::

           @phony
           def initialize_logging(config: Config) -> None:
               logging.basicConfig(level=config.log_level)

    2. **类型安全**：phony 资源的类型应为 ``None``，访问时返回 ``None``::

           root.initialize_logging  # 触发副作用，返回 None

    3. **Semigroup 语义**：多个 phony 定义合并时，所有副作用均会执行。
       **重要**：用户必须确保多个 phony 定义满足交换律，不得依赖执行顺序::

           @phony
           def setup():
               register_handler_a()  # 必须与其他 setup 的副作用相互独立

           @phony
           def setup():
               register_handler_b()  # 必须与其他 setup 的副作用相互独立

    4. **依赖追踪**：phony 资源可以依赖其他资源，确保依赖在副作用执行前已就绪::

           @phony
           def warmup_cache(database: Database, cache: Cache) -> None:
               cache.populate_from(database)

    5. **与 ``@resource`` 的区别**：

       - ``@resource`` 返回值会被缓存并可被其他资源依赖
       - ``@phony`` 返回 ``None``，主要目的是触发副作用，多个定义作为 Semigroup 合并

    6. **装饰器表更新**：

       +-------------------+----------+---------+------------------------------------------+
       | @phony            | Yes      | Yes     | Semigroup for side-effect-only resources |
       +-------------------+----------+---------+------------------------------------------+

.. todo::
    支持通过 type annotation 指定 ``PurePath`` 来定位依赖。

    当前依赖解析基于参数名在符号表中查找，需要遍历闭包层级。通过 ``Annotated`` 和
    ``PurePath`` 可以显式指定依赖的相对路径，避免符号表查找::

        # 期望支持的语法
        @resource
        def connection_pool(
            database_url: Annotated[URL, ResourceReference.from_pure_path(PurePath("../../config/database_url"))]
        ):
            return create_connection_pool(database_url)

        # 大致等价于当前语法
        @resource
        def connection_pool(config: Proxy):
            return create_connection_pool(config.database_url)

    前者显式指定了 ``database_url`` 的位置，后者需要在符号表查找 ``config`` 所在的闭包层级。

    ``ResourceReference`` 的优势在于可以访问不在词法作用域中的资源。即使 ``config`` 不在当前词法作用域的
    符号表中，``../../config`` 仍然可以通过路径直接定位到它。

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

    # Result: Proxy with both foo and bar resources (merged)

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

Complex Path Access via Proxy
------------------------------

To access resources via complex paths, you must use an explicit :class:`Proxy` parameter::

    @resource
    def my_callable(uncle: Proxy) -> float:
        return uncle.path.to.resource

This searches the lexical scope chain for the first :class:`Proxy` that defines a resource
named ``uncle``, then accesses ``path.to.resource`` under that :class:`Proxy`.

Proxy-Returning Resources as Symbolic Links
--------------------------------------------

If a callable returns a :class:`Proxy`, that resource acts like a symbolic link
(similar to https://github.com/mxmlnkn/ratarmount/pull/163)::

    @resource
    def my_scope(uncle: Proxy) -> Proxy:
        return uncle.path.to.another_scope

This finds the first :class:`Proxy` in the lexical scope that defines ``uncle``, then accesses
nested resources through that :class:`Proxy`.

Same-Name Dependency (Extending Outer Definitions)
---------------------------------------------------

When a parameter name matches the resource name, it skips the current :class:`Proxy` and
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
or objects, which are union-mounted into a unified root :class:`Proxy`, similar to
https://github.com/mxmlnkn/ratarmount/pull/163.

Parameter Injection Pattern
============================

Concept
-------

A resource can be defined **solely** by :func:`patch`, :func:`patch_many`, or :func:`extern`
decorators, without a base definition from :func:`resource` or :func:`merge`. This is
the **parameter injection pattern** - a way to declare that a value should be provided from
an outer scope via :class:`InstanceProxy` or :meth:`StaticProxy.__call__`.

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
to be provided via :meth:`StaticProxy.__call__`. The ``@extern`` decorator is syntactic sugar
that makes the intent clearer.

How It Works
------------

When a parameter-only resource is accessed:

1. The resource name is found in the symbol table (registered by ``@extern`` or ``@patch``)
2. The base value is looked up from :class:`InstanceProxy` (created via ``StaticProxy.__call__``)
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

Proxy as Callable
=================

Every :class:`Proxy` object is also callable, supporting direct parameter injection.

Implementation
--------------

:class:`Proxy` implements ``__call__(**kwargs)``, returning a new :class:`Proxy` of the same type
creating an :class:`InstanceProxy` that stores kwargs directly for lookup.

Example::

    # Create a Proxy and inject values using mount
    @scope()
    class Config:
        @extern
        def setting(): ...
        @extern
        def count(): ...

    proxy = mount(Config)
    new_proxy = proxy(setting="value", count=42)

    # Access injected values
    assert new_proxy.setting == "value"
    assert new_proxy.count == 42

Primary Use Case
----------------

The primary use of Proxy as Callable is to provide base values for parameter injection.
By using :meth:`Proxy.__call__` in an outer scope to inject parameter values, resources in
modules can access these values via symbol table lookup::

    # Provide base value in outer scope via mount
    @scope()
    class Config:
        @extern
        def db_config(): ...

    outer_proxy = mount(Config)(db_config={"host": "localhost", "port": "5432"})

    outer_scope: LexicalScope = (outer_proxy,)

    # Resources in modules can obtain this value via same-named parameter
    @scope()
    class Database:
        @extern
        def db_config(): ...

        @resource
        def connection(db_config: dict) -> str:
            return f"{db_config['host']}:{db_config['port']}"

Callables can be used not only to define resources but also to define and transform Proxy objects.
"""

from __future__ import annotations

import ast
from enum import Enum, auto
import importlib
import logging
import os
import importlib.util
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from functools import cached_property, reduce
from inspect import signature
from pathlib import PurePath
from types import MappingProxyType, ModuleType
from typing import (
    Any,
    AsyncContextManager,
    Awaitable,
    Callable,
    ChainMap,
    Concatenate,
    ContextManager,
    Final,
    Hashable,
    Generic,
    Iterable,
    Iterator,
    Literal,
    Mapping,
    MutableMapping,
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

P = ParamSpec("P")


@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class Mixin(ABC):
    """Base class for dependency graphs supporting O(1) equality comparison.

    Equal graphs are interned to the same object instance within the same root,
    making equality comparison a simple identity check (O(1) instead of O(n)).

    This class is immutable and hashable, suitable for use as dictionary keys.

    .. todo:: 继承 ``Mapping[Hashable, EvaluatorGetter]``。
    """

    intern_pool: Final[weakref.WeakValueDictionary[Hashable, "NestedMixin"]] = field(
        default_factory=weakref.WeakValueDictionary
    )


class SymbolSentinel(Enum):
    SYNTHETIC = auto()
    """
    Sentinel indicating that the dependency graph is synthetic and does not correspond to a real symbol.
    """


@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class StaticMixin(Mixin):
    """
    .. todo:: 实现 ``__getitem__`` 用于懒创建子依赖图。
    .. todo:: 实现 ``__call__(lexical_scope: LexicalScope) -> _ProxySemigroup``，
              使 ``ChildMixin`` 成为 ``Callable[[LexicalScope], _ProxySemigroup]``。
    """

    symbol: Final["_MixinSymbol | SymbolSentinel"]
    """
    The symbol for this dependency graph, providing cached symbol resolution.
    Subclasses (RootMixin, ChildMixin) must define this field.
    """

    _cached_instance_mixin: weakref.ReferenceType["InstanceChildMixin"] | None = field(
        default=None, init=False
    )
    """
    Cache for the corresponding InstanceChildMixin.
    """

    bases: Sequence["Mixin[Any]"] = field(default_factory=tuple)
    """
    Mapping from dependency graph paths to their corresponding symbols.
    Corresponds one-to-one with Proxy.mixins keys.

    .. todo:: 拆分为 ``symbol: _Symbol`` (单个) + ``base_symbols: ChainMap[ChildMixin, _Symbol]``，
              ``symbols`` 改为 ``cached_property`` 合并两者。
    """

    @property
    def proxy_definition(self) -> "_MixinDefinition":
        """The definition that describes resources, patches, and nested scopes for this dependency graph."""
        if isinstance(self.symbol, SymbolSentinel):
            raise ValueError(
                f"proxy_definition is not available for merged dependency graphs (symbol={self.symbol})"
            )
        return self.symbol.proxy_definition


Evaluator: TypeAlias = "Merger | Patcher"
"""A Merger or Patcher that participates in resource evaluation."""

EvaluatorGetter: TypeAlias = Callable[["LexicalScope"], Evaluator]
"""A callable that retrieves an Evaluator from a LexicalScope context."""


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class RootMixin(StaticMixin):
    """
    Root of a dependency graph.

    Each RootMixin instance has its own intern pool for interning
    ChildMixin nodes within that dependency graph.

    """


@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class NestedMixin(StaticMixin):
    """Non-empty dependency graph node.

    Uses object.__eq__ and object.__hash__ (identity-based) for O(1) comparison.
    This works because interned graphs within the same outer are the same object.

    Implements ``Callable[[LexicalScope], _ProxySemigroup]`` to resolve resources
    from a lexical scope into a proxy semigroup.
    """

    outer: Final[Mixin]
    name: Final[Hashable]

    def __call__(self, lexical_scope: LexicalScope) -> "_ProxySemigroup":
        """
        Resolve resources from the given lexical scope into a _ProxySemigroup.

        This method creates a proxy factory that:
        1. Creates a mixin from this definition's proxy_definition
        2. Includes mixins from any extended proxies (via extend references)
        3. Returns a _ProxySemigroup that can merge with other proxies

        .. todo:: Phase 9: 用 ``ChainMap`` 替代 ``generate_all_mixin_items``。
        """

        def proxy_factory() -> StaticProxy:
            assert (
                lexical_scope
            ), "lexical_scope must not be empty when resolving resources"

            def generate_all_mixin_items() -> (
                Iterator[tuple[StaticMixin, LexicalScope]]
            ):
                """
                Generate all mixin items for the proxy, including:
                - LexicalScope from this definition, keyed by proxy's mixin
                - LexicalScopes from extended proxies, preserving their original keys
                """
                yield (self, lexical_scope)
                for reference in self.proxy_definition.extend:
                    extended_proxy = _resolve_resource_reference(
                        reference=reference,
                        lexical_scope=lexical_scope,
                        forbid_instance_proxy=True,
                    )
                    yield from extended_proxy.mixins.items()

            return self.proxy_definition.proxy_class(
                mixins=dict(generate_all_mixin_items()),
                mixin=self,
            )

        return _ProxySemigroup(
            proxy_factory=proxy_factory,
            access_path_outer=self.outer,
            name=self.name,
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class InstanceChildMixin(Mixin):
    """Non-empty dependency graph node for InstanceProxy.

    Uses object.__eq__ and object.__hash__ (identity-based) for O(1) comparison.
    This works because interned graphs with equal head within the same outer
    are the same object.
    """

    prototype: Final[StaticMixin]
    """
    The static dependency graph that this instance is based on.
    """


Resource = NewType("Resource", object)


class Proxy(Mapping[Hashable, "Node"], ABC):
    """
    A Proxy represents resources available via attributes or keys.

    There are two types of proxies:

    - ``StaticProxy``: Represents class/module level static definitions.
      Contains mixins and supports ``__call__`` to create instances.
    - ``InstanceProxy``: Created via ``StaticProxy.__call__``.
      Stores kwargs directly and delegates to base proxy for other lookups.

    .. todo::
        我希望把Proxy/CachedProxy/WeakCachedProxy合并成一个类，按需提供ResourceConfig的26种组合行为。

        我希望可以通过新增的一些decorator提供 ResourceConfig 的配置。注意这个配置是静态的不依赖于 Proxy 和 Scope，且可能将来会被Symbol编译进字节码里。
        ```
        @dataclass
        class BuilderDefinition:
            bind_lexical_scope: Callable[[LexicalScope, str], Callable[[Proxy, ResourceConfig], Evaluator]]
            config: ResourceConfig
            '''
            默认的config由``inspect.signature``推断而来，可以由注解修改
            '''

        ```


        用同一套Merger/Patcher接口来处理context manager/async，但是`TResult`的类型取决于ResourceConfig，可能是Awaitable/ContextManager/AsyncContextManager，或是直接的同步类型。`@resource`的`TPatch`的类型也取决于ResourceConfig，可能是`Endofunction`/`ContextManagerEndofunction`/`AsyncEndofunction`/`AsyncContextManagerEndofunction`。也就是说同一套Merger/Patcher接口可以处理同步/异步/上下文管理器的情况。

    .. todo::
        支持定义 method，需要动态生成类。

        当前实现通过 ``__getattr__`` 拦截属性访问来提供资源，但 ``__getattr__`` 不是真正的
        method，无法用于定义 dunder 方法（如 ``__str__``、``__repr__``、``__eq__`` 等）。
        Python 的 dunder 方法查找直接在类的 ``__dict__`` 中进行，不经过 ``__getattr__``。

        问题示例::

            @scope()
            class MyScope:
                @resource
                def __str__() -> str:
                    return "custom string representation"

            root = mount(MyScope)
            str(root)  # 不会调用自定义的 __str__，而是使用 Proxy 默认的 __str__

    """

    @property
    @abstractmethod
    def mixins(
        self,
    ) -> Mapping[StaticMixin, LexicalScope]:
        """The mixins that provide resources for this proxy, keyed by mixin.

        Each proxy's own properties (not from extend=) are stored at
        mixins[self.mixin]. Extended proxies contribute their mixins
        with their original mixin keys.

        .. todo:: 改用 ``ChainMap`` 代替 ``dict``。
        """
        ...

    mixin: "NestedMixin | InstanceChildMixin"
    """The runtime access path from root to this proxy, in reverse order.

    This path reflects how the proxy was accessed at runtime, not where
    it was statically defined. For example, root.object1.MyInner and
    root.object2.MyInner should have different mixins even if
    MyInner is defined in the same place.
    """

    def __getitem__(self, key: Hashable) -> "Node":
        def generate_resource() -> Iterator[Evaluator]:
            for mixin, lexical_scope in self.mixins.items():
                try:
                    factory_or_patch = _mixin_getitem(mixin, lexical_scope, key)
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
        for mixin in self.mixins.keys():
            if isinstance(mixin.symbol, SymbolSentinel):
                # Merged dependency graphs don't have their own keys
                continue
            for key in mixin.symbol.keys():
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
            *super(Proxy, self).__dir__(),
        )


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class StaticProxy(Proxy, ABC):
    """
    A static proxy representing class/module level definitions.

    StaticProxy stores mixins directly and supports ``__call__`` to create
    InstanceProxy with additional kwargs.
    """

    mixins: Mapping[StaticMixin, LexicalScope]  # type: ignore[misc]
    mixin: StaticMixin  # type: ignore[misc]

    def __call__(self, **kwargs: object) -> "InstanceProxy":
        """
        Create an InstanceProxy with the given kwargs.

        .. todo:: Phase 2: Pass ``symbol`` and ``base_symbols``
                  when creating ``InstanceChildMixin``.
        """
        # Get or create InstanceChildMixin (memoized via weak reference)
        cached_ref = self.mixin._cached_instance_mixin
        instance_path = cached_ref() if cached_ref is not None else None
        if instance_path is None:
            instance_path = InstanceChildMixin(prototype=self.mixin)
            self.mixin._cached_instance_mixin = weakref.ref(instance_path)

        return InstanceProxy(
            base_proxy=self,
            kwargs=kwargs,
            mixin=instance_path,
        )


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class InstanceProxy(Proxy):
    """
    An instance proxy created via StaticProxy.__call__.

    InstanceProxy stores kwargs directly and checks them first during lookup,
    then delegates to the base proxy for other resources.

    .. note:: kwargs keys are bounded by str because Python's **kwargs only accepts string keys.
    """

    base_proxy: Final[StaticProxy]
    kwargs: Final[Mapping[str, object]]
    mixin: InstanceChildMixin  # type: ignore[misc]

    @property
    @override
    def mixins(
        self,
    ) -> Mapping[StaticMixin, LexicalScope]:
        return self.base_proxy.mixins

    @override
    def __getitem__(self, key: Hashable) -> Node:
        if isinstance(key, str) and key in self.kwargs:
            value = self.kwargs[key]

            def generate_resource() -> Iterator[Evaluator]:
                # Yield the kwargs value as a Merger
                yield _EndofunctionMerger(base_value=cast(Resource, value))
                # Also collect any Patchers from mixins
                for mixin, lexical_scope in self.mixins.items():
                    try:
                        factory_or_patch = _mixin_getitem(mixin, lexical_scope, key)
                    except KeyError:
                        continue
                    yield factory_or_patch(self)

            return _evaluate_resource(resource_generator=generate_resource)
        return super(InstanceProxy, self).__getitem__(key)

    @override
    def __iter__(self) -> Iterator[Hashable]:
        for key in self.kwargs:
            yield key
        for key in super(InstanceProxy, self).__iter__():
            if key not in self.kwargs:
                yield key

    @override
    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __call__(self, **kwargs: object) -> "InstanceProxy":
        merged_kwargs: Mapping[str, object] = {**self.kwargs, **kwargs}
        return InstanceProxy(
            base_proxy=self.base_proxy,
            kwargs=merged_kwargs,
            mixin=self.mixin,
        )


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class CachedProxy(StaticProxy[str]):
    """A StaticProxy with cached resource lookups."""

    _cache: MutableMapping[str, "Node"] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @override
    def __getitem__(self, key: str) -> "Node":
        """
        .. note:: This method uses the two-arg super() as a workaround for https://github.com/python/cpython/pull/124455
        """
        if key not in self._cache:
            value = super(CachedProxy, self).__getitem__(key)
            self._cache[key] = value
            return value
        else:
            return self._cache[key]


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class WeakCachedScope(CachedProxy):
    """A CachedProxy with weak reference caching."""

    _cache: MutableMapping[str, "Node"] = field(
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


LexicalScope: TypeAlias = Sequence[Proxy]
"""
A sequence of proxies representing the lexical scope, starting from the outermost proxy to the innermost proxy.
"""


class ChainMapSentinel(Enum):
    EMPTY = auto()
    """
    This is a workaround for Python's quirk where a ChainMap always has at least one mapping. e.g. `len(ChainMap().maps)` is 1, not 0.
    """


SymbolTable: TypeAlias = ChainMap[Hashable, "_Symbol"] | Literal[ChainMapSentinel.EMPTY]
"""
A mapping from resource names to symbols that provide getters for lexical scope lookups.

.. note:: NEVER ever modify a SymbolTable in-place. Always create a new ChainMap layer to add new definitions.
"""


Node: TypeAlias = Resource | Proxy
TPatch_co = TypeVar("TPatch_co", covariant=True)
TPatch_contra = TypeVar("TPatch_contra", contravariant=True)
TResult_co = TypeVar("TResult_co", covariant=True)


class Merger(Generic[TPatch_contra, TResult_co], ABC):
    @abstractmethod
    def create(self, patches: Iterator[TPatch_contra]) -> TResult_co: ...


class Patcher(Iterable[TPatch_co], ABC):
    """
    An Patcher provides extra data to be applied to a Node created by a ``Merger``.
    """


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FunctionPatcher(Patcher[TPatch_co]):
    patch_generator: Callable[[], Iterator[TPatch_co]]

    def __iter__(self) -> Iterator[TPatch_co]:
        return self.patch_generator()


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FunctionMerger(Merger[TPatch_contra, TResult_co]):
    """Merger that applies custom aggregation function to patches."""

    aggregation_function: Callable[[Iterator[TPatch_contra]], TResult_co]

    @override
    def create(self, patches: Iterator[TPatch_contra]) -> TResult_co:
        return self.aggregation_function(patches)


TResult = TypeVar("TResult")
TProxy = TypeVar("TProxy", bound=StaticProxy)


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _EndofunctionMerger(
    Generic[TResult], Merger[Callable[[TResult], TResult], TResult]
):
    """Merger that applies patches as endofunctions via reduce."""

    base_value: TResult

    @override
    def create(self, patches: Iterator[Callable[[TResult], TResult]]) -> TResult:
        return reduce(lambda acc, endo: endo(acc), patches, self.base_value)


def _mixin_getitem(
    mixin: StaticMixin,
    lexical_scope: LexicalScope,
    key: Hashable,
    /,
) -> Callable[[Proxy], Evaluator]:
    """
    Get a factory function from a dependency graph by key.

    Calls ``mixin.symbol[key](mixin)`` to get the
    second-level callable, passing the mixin's mixin (not the
    proxy's mixin from lexical_scope).
    """
    first_level = mixin.symbol.cached_resolve_symbols(key)
    resolved_function = first_level(mixin)

    def bind_proxy(proxy: Proxy) -> Evaluator:
        inner_lexical_scope: LexicalScope = (*lexical_scope, proxy)
        evaluator = resolved_function(inner_lexical_scope)
        # If evaluator is a _ProxySemigroup, set access_path_outer to the proxy's mixin
        if isinstance(evaluator, _ProxySemigroup):
            return replace(evaluator, access_path_outer=proxy.mixin)
        return evaluator

    return bind_proxy


@dataclass(kw_only=True, slots=True, weakref_slot=True)
class _Symbol(ABC):
    @property
    @abstractmethod
    def depth(self) -> int:
        """
        The depth of the symbol in the scope hierarchy.
        Used for resolving same-name dependencies.
        """
        ...

    @property
    @abstractmethod
    def resource_name(self) -> str:
        """
        The resource name associated with this symbol.
        """
        ...

    getter: Callable[[LexicalScope], "Node"] = field(init=False)

    def __post_init__(self) -> None:
        self.getter = _make_jit_getter(self.resource_name, self.depth)


@dataclass(kw_only=True, slots=True, weakref_slot=True)
class _SimpleSymbol(_Symbol):
    """
    Concrete implementation of _Symbol for individual resource entries in SymbolTable.
    """

    _depth: Final[int]
    _resource_name: Final[str]

    @property
    @override
    def depth(self) -> int:
        return self._depth

    @property
    @override
    def resource_name(self) -> str:
        return self._resource_name


@dataclass(kw_only=True, slots=True, weakref_slot=True)
class _MixinSymbol(
    _Symbol,
    Mapping[Hashable, Callable[[Mixin], Callable[[LexicalScope], Evaluator]]],
):
    """
    Mapping that caches resolve_symbols results for definitions in a namespace.

    Implements _Symbol to provide depth and resource_name for the namespace itself.

    .. todo:: Also compiles the proxy class into Python bytecode.

    .. note:: _MixinSymbol instances are shared among all mixins created from the same
        _MixinDefinition (the Python class decorated with @scope()). For example::

            root.Outer(arg="v1").Inner.mixins[...].symbol
            root.Outer(arg="v2").Inner.mixins[...].symbol
            root.Outer.Inner.mixins[...].symbol
            root.object1(arg="v").Inner.mixins[...].symbol  # object1 extends Outer

        All share the same _MixinSymbol because they reference the same ``Inner`` class.
        The _MixinSymbol is created once in _MixinDefinition.resolve_symbols and captured
        in the closure, tied to the definition itself, not to the access path.
    """

    name: Final[str]
    proxy_definition: Final["_MixinDefinition"]
    symbol_table: Final[SymbolTable]
    cache: Final[
        dict[Hashable, Callable[[Mixin], Callable[[LexicalScope], Evaluator]]]
    ] = field(default_factory=dict)

    @property
    @override
    def resource_name(self) -> str:
        return self.name

    @property
    @override
    def depth(self) -> int:
        if self.symbol_table is ChainMapSentinel.EMPTY:
            return 0
        return len(self.symbol_table.maps)

    def cached_resolve_symbols(
        self, key: Hashable
    ) -> Callable[[Mixin], Callable[[LexicalScope], Evaluator]]:
        if key in self.cache:
            return self.cache[key]
        val = self.proxy_definition.__getitem__(key)
        outer = val.resolve_symbols(self.symbol_table, cast(str, key))
        self.cache[key] = outer
        return outer

    def __iter__(self) -> Iterator[str]:
        return self.proxy_definition.__iter__()

    def __len__(self) -> int:
        return sum(1 for _ in self)
    
    def __getitem__(self, key: Hashable) -> Callable[[Mixin], Callable[[LexicalScope], Evaluator]]:
        return self.cached_resolve_symbols(key)


def _evaluate_resource(
    resource_generator: Callable[[], Iterator[Evaluator]],
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
    def resolve_symbols(
        self, symbol_table: "SymbolTable", name: str, /
    ) -> Callable[[Mixin], Callable[[LexicalScope], Evaluator]]:
        """
        Resolve symbols in the definition and return a two-layer callable.
        First layer takes Mixin, second layer takes LexicalScope.
        """
        raise NotImplementedError()


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class MergerDefinition(Definition, Generic[TPatch_contra, TResult_co]):
    is_eager: bool = False
    is_local: bool = False

    @abstractmethod
    def resolve_symbols(
        self, symbol_table: "SymbolTable", name: str, /
    ) -> Callable[[Mixin], Callable[[LexicalScope], Merger]]:
        raise NotImplementedError()


class PatcherDefinition(Definition, Generic[TPatch_co]):
    @abstractmethod
    def resolve_symbols(
        self, symbol_table: "SymbolTable", name: str, /
    ) -> Callable[[Mixin], Callable[[LexicalScope], Patcher]]:
        raise NotImplementedError()


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _MergerDefinition(MergerDefinition[TPatch_contra, TResult_co]):
    """Definition for merge decorator."""

    function: Callable[..., Callable[[Iterator[TPatch_contra]], TResult_co]]

    @override
    def resolve_symbols(
        self, symbol_table: "SymbolTable", name: str, /
    ) -> Callable[[Mixin], Callable[[LexicalScope], Merger[TPatch_contra, TResult_co]]]:
        jit_compiled_function = _resolve_dependencies_jit(
            symbol_table=symbol_table,
            function=self.function,
            name=name,
        )

        def with_mixin(
            _mixin: Mixin,
        ) -> Callable[[LexicalScope], Merger[TPatch_contra, TResult_co]]:
            def resolve_lexical_scope(
                lexical_scope: LexicalScope,
            ) -> Merger[TPatch_contra, TResult_co]:
                aggregation_function = jit_compiled_function(lexical_scope)
                return FunctionMerger(aggregation_function=aggregation_function)

            return resolve_lexical_scope

        return with_mixin


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _ResourceDefinition(
    Generic[TResult], MergerDefinition[Callable[[TResult], TResult], TResult]
):
    """Definition for resource decorator."""

    function: Callable[..., TResult]

    @override
    def resolve_symbols(self, symbol_table: "SymbolTable", name: str, /) -> Callable[
        [Mixin],
        Callable[[LexicalScope], Merger[Callable[[TResult], TResult], TResult]],
    ]:
        jit_compiled_function = _resolve_dependencies_jit(
            symbol_table=symbol_table,
            function=self.function,
            name=name,
        )

        def with_mixin(
            _mixin: Mixin,
        ) -> Callable[[LexicalScope], Merger[Callable[[TResult], TResult], TResult]]:
            def resolve_lexical_scope(
                lexical_scope: LexicalScope,
            ) -> Merger[Callable[[TResult], TResult], TResult]:
                base_value = jit_compiled_function(lexical_scope)
                return _EndofunctionMerger(base_value=base_value)

            return resolve_lexical_scope

        return with_mixin


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _SinglePatchDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patch decorator (single patch)."""

    function: Callable[..., TPatch_co]

    @override
    def resolve_symbols(
        self, symbol_table: "SymbolTable", name: str, /
    ) -> Callable[[Mixin], Callable[[LexicalScope], Patcher[TPatch_co]]]:
        jit_compiled_function = _resolve_dependencies_jit(
            symbol_table=symbol_table,
            function=self.function,
            name=name,
        )

        def with_mixin(
            _mixin: Mixin,
        ) -> Callable[[LexicalScope], Patcher[TPatch_co]]:
            def resolve_lexical_scope(
                lexical_scope: LexicalScope,
            ) -> Patcher[TPatch_co]:
                def patch_generator() -> Iterator[TPatch_co]:
                    yield jit_compiled_function(lexical_scope)

                return FunctionPatcher(patch_generator=patch_generator)

            return resolve_lexical_scope

        return with_mixin


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _MultiplePatchDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patches decorator (multiple patches)."""

    function: Callable[..., Iterable[TPatch_co]]

    @override
    def resolve_symbols(
        self, symbol_table: "SymbolTable", name: str, /
    ) -> Callable[[Mixin], Callable[[LexicalScope], Patcher[TPatch_co]]]:
        jit_compiled_function = _resolve_dependencies_jit(
            symbol_table=symbol_table,
            function=self.function,
            name=name,
        )

        def with_mixin(
            _mixin: Mixin,
        ) -> Callable[[LexicalScope], Patcher[TPatch_co]]:
            def resolve_lexical_scope(
                lexical_scope: LexicalScope,
            ) -> Patcher[TPatch_co]:
                def patch_generator() -> Iterator[TPatch_co]:
                    return (yield from jit_compiled_function(lexical_scope))

                return FunctionPatcher(patch_generator=patch_generator)

            return resolve_lexical_scope

        return with_mixin


DefinitionMapping: TypeAlias = Mapping[
    str, Callable[[LexicalScope], Callable[[Proxy], Evaluator]]
]


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _ProxySemigroup(Merger[StaticProxy, StaticProxy], Patcher[StaticProxy]):
    """
    Semigroup for merging Proxy instances from extended scopes.

    .. todo:: 改为只支持 ``StaticProxy`` 的合并，禁止 ``InstanceProxy`` 的合并。

        应将类型签名改为 ``Merger[StaticProxy, StaticProxy]``，并在 ``create``
        方法中添加断言确保不会传入 ``InstanceProxy``。
    """

    proxy_factory: Final[Callable[[], StaticProxy]]
    access_path_outer: Final[Mixin]
    name: Final[Hashable]

    @override
    def create(self, patches: Iterator[StaticProxy]) -> StaticProxy:
        """
        Create a merged Proxy from factory and patches.

        .. todo:: Phase 9: 用 ``ChainMap`` 替代 ``generate_all_mixin_items``。
        """

        def all_proxies() -> Iterator[StaticProxy]:
            yield from self
            return (yield from patches)

        proxies_tuple = tuple(all_proxies())
        match proxies_tuple:
            case (single_proxy,) if (
                isinstance(single_proxy.mixin, NestedMixin)
                and single_proxy.mixin.outer == self.access_path_outer
            ):
                mixin = single_proxy.mixin
            case ():
                raise AssertionError(" at least one proxy expected")
            case _:
                # Get or create mixin with correct outer from intern pool
                existing = self.access_path_outer.intern_pool.get(self.name)
                if existing is not None:
                    mixin = existing
                else:
                    mixin = NestedMixin(
                        outer=self.access_path_outer,
                        symbol=SymbolSentinel.SYNTHETIC,
                        name=self.name,
                    )
                    self.access_path_outer.intern_pool[self.name] = mixin

        winner_class = _calculate_most_derived_class(*(type(p) for p in proxies_tuple))

        def generate_all_mixin_items() -> Iterator[tuple[StaticMixin, LexicalScope]]:
            for proxy in proxies_tuple:
                yield from proxy.mixins.items()

        all_mixin_items = list(generate_all_mixin_items())
        merged_mixins = dict(all_mixin_items)
        _logger.debug(
            "proxies_count=%(proxies_count)d "
            "total_mixin_items=%(total_mixin_items)d "
            "unique_after_dict=%(unique_after_dict)d",
            {
                "proxies_count": len(proxies_tuple),
                "total_mixin_items": len(all_mixin_items),
                "unique_after_dict": len(merged_mixins),
            },
        )

        return winner_class(
            mixins=merged_mixins,
            mixin=mixin,
        )

    @override
    def __iter__(self) -> Iterator[StaticProxy]:
        proxy = self.proxy_factory()
        assert isinstance(
            proxy, StaticProxy
        ), f"proxy must be StaticProxy, got {type(proxy)}"
        yield proxy


def _resolve_resource_reference(
    reference: "ResourceReference[Hashable]",
    lexical_scope: LexicalScope,
    forbid_instance_proxy: bool = False,
) -> Proxy:
    """
    Resolve a ResourceReference to a Proxy using the given lexical scope.

    For RelativeReference:
        - Navigate up `levels_up` levels from the innermost proxy
        - Then navigate down through `parts` by accessing attributes

    For AbsoluteReference:
        - Start from the root (outermost proxy)
        - Navigate down through `parts` by accessing attributes

    :param forbid_instance_proxy: If True, raises TypeError if any step in the
        path resolves to an InstanceProxy. Used by extend to prevent referencing
        paths through InstanceProxy (e.g., object1.MyInner where object1 is an
        InstanceProxy).

    .. todo:: 添加 ``_resolve_mixin_reference`` 辅助函数，类似本函数，
              但参数为 ``mixin: Mixin`` 而非 ``lexical_scope: LexicalScope``，
              返回类型为 ``Callable[[LexicalScope], Evaluator]``
              （实际上是 ``ChildMixin``，它本质上是特殊的
              ``Callable[[LexicalScope], Evaluator]``）。

              该函数用于在 dependency graph 中查找静态的 ``Callable[[LexicalScope], Evaluator]``。
              与 ``_resolve_resource_reference`` 的区别在于：

              - ``_resolve_resource_reference``: 运行时解析，遍历 lexical_scope 中的 Proxy 对象
              - ``_resolve_mixin_reference``: 编译时解析，遍历 mixin 中的
                ``ChildMixin``，返回可被 JIT 缓存的 callable

              签名示例::

                  def _resolve_mixin_reference(
                      reference: ResourceReference[TKey],
                      mixin: Mixin,
                  ) -> Callable[[LexicalScope], Evaluator]:
                      ...
    """
    match reference:
        case RelativeReference(levels_up=levels_up, path=parts):
            if levels_up > len(lexical_scope):
                raise ValueError(
                    f"Cannot navigate {levels_up} levels up from scope of depth {len(lexical_scope)}"
                )
            # Navigate up: levels_up=0 means innermost (last), levels_up=1 means outer, etc.
            scope_index = len(lexical_scope) - 1 - levels_up
            current: Proxy | Resource = lexical_scope[scope_index]
        case AbsoluteReference(path=parts):
            if not lexical_scope:
                raise ValueError(
                    "Cannot resolve absolute reference with empty lexical scope"
                )
            current = lexical_scope[0]
        case _ as unreachable:
            assert_never(unreachable)

    # Navigate through parts
    traversed_parts: list[Hashable] = []
    for part in parts:
        resolved = current[part]
        if not isinstance(resolved, Proxy):
            raise TypeError(
                f"Expected Proxy while resolving reference, got {type(resolved)} at part '{part}'"
            )
        traversed_parts.append(part)
        if forbid_instance_proxy and isinstance(resolved, InstanceProxy):
            raise TypeError(
                f"Cannot extend through InstanceProxy. "
                f"Path {'.'.join(str(p) for p in traversed_parts)} resolved to an InstanceProxy."
            )
        current = resolved

    if not isinstance(current, Proxy):
        raise TypeError(f"Final resolved value is not a Proxy: {type(current)}")
    return current


@dataclass(frozen=True, kw_only=True)
class _MixinDefinition(
    Mapping[Hashable, Definition],
    MergerDefinition[Proxy, Proxy],
    PatcherDefinition[Proxy],
):
    """Base class for proxy definitions that create Proxy instances from underlying objects."""

    proxy_class: type[StaticProxy]
    underlying: object
    extend: tuple["ResourceReference[Hashable]", ...] = ()

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

    def resolve_symbols(
        self, symbol_table: SymbolTable, name: str, /
    ) -> Callable[[Mixin], NestedMixin]:
        """
        Resolve symbols for this definition given the symbol table and resource name.

        Returns a function that takes an outer Mixin and returns a
        ChildMixin that implements ``Callable[[LexicalScope], _ProxySemigroup]``.

        .. todo:: Phase 2: Add ``base_symbols`` parameter to ``ChildMixin``
                  for inherited symbols from extended scopes.
        """
        inner_symbol_table: SymbolTable = _extend_symbol_table_jit(
            outer=symbol_table, names=self.__iter__()
        )
        symbol = _MixinSymbol(
            name=name,
            proxy_definition=self,
            symbol_table=inner_symbol_table,
        )

        def with_mixin(
            outer_mixin: Mixin,
        ) -> NestedMixin:
            """
            Create or retrieve a memoized ChildMixin for the given outer dependency graph.

            Memoization ensures that the same ChildMixin instance is reused
            for the same (outer_mixin, name) pair, enabling O(1) identity-based
            equality comparison.
            """
            intern_pool = outer_mixin.intern_pool
            existing = intern_pool.get(name)
            if existing is not None:
                return existing
            proxy_mixin = NestedMixin(
                outer=outer_mixin,
                symbol=symbol,
                name=name,
            )
            intern_pool[name] = proxy_mixin
            _logger.debug(
                "name=%(name)r "
                "underlying=%(underlying)r "
                "outer_name=%(outer_name)r",
                {
                    "name": name,
                    "underlying": self.underlying,
                    "outer_name": getattr(outer_mixin, "name", "ROOT"),
                },
            )
            return proxy_mixin

        return with_mixin


@dataclass(frozen=True, kw_only=True)
class _NamespaceDefinition(_MixinDefinition):
    """
    A definition that creates a Proxy from an object's attributes.
    Implements lazy evaluation via resolve_symbols.
    """


@dataclass(frozen=True, kw_only=True)
class _PackageDefinition(_MixinDefinition):
    """A definition for packages that discovers submodules via pkgutil."""

    get_module_proxy_class: Callable[[ModuleType], type[StaticProxy]]
    underlying: ModuleType

    def __iter__(self) -> Iterator[str]:
        yield from super(_PackageDefinition, self).__iter__()

        for mod_info in pkgutil.iter_modules(self.underlying.__path__):
            yield mod_info.name

    @override
    def __getitem__(self, key: Hashable) -> Definition:
        """Get a Definition by key name, including lazily imported submodules."""
        # 1. Try parent (attributes that are Definition)
        try:
            return super(_PackageDefinition, self).__getitem__(key)
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
            return _PackageDefinition(
                underlying=submod,
                proxy_class=self.get_module_proxy_class(submod),
                get_module_proxy_class=self.get_module_proxy_class,
            )
        else:
            return _NamespaceDefinition(
                underlying=submod,
                proxy_class=self.get_module_proxy_class(submod),
            )


def scope(
    *,
    proxy_class: type[StaticProxy] = CachedProxy,
    extend: Iterable["ResourceReference[Hashable]"] = (),
) -> Callable[[object], _NamespaceDefinition]:
    """
    Decorator that converts a class into a NamespaceDefinition.
    Nested classes MUST be decorated with @scope() to be included as sub-scopes.

    Note: Always use @scope() with parentheses, not @scope without parentheses.

    :param proxy_class: The Proxy subclass to use for this scope.
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
    extend_tuple = tuple(extend)

    def wrapper(c: object) -> _NamespaceDefinition:
        return _NamespaceDefinition(
            underlying=c,
            proxy_class=proxy_class,
            extend=extend_tuple,
        )

    return wrapper


def _parse_package(
    module: ModuleType,
    get_module_proxy_class: Callable[[ModuleType], type[StaticProxy]],
) -> _MixinDefinition:
    """
    Parses a module into a NamespaceDefinition.

    Only module-level attributes explicitly decorated with @resource, @patch, @patch_many, or @merge are included.
    Nested modules and packages are recursively parsed with lazy loading.

    IMPORTANT: Bare callables (without decorators) are NOT automatically included.
    Users must explicitly mark all injectable definitions with appropriate decorators.

    For packages (modules with __path__), uses pkgutil.iter_modules to discover submodules
    and importlib.import_module to lazily import them when accessed.
    """
    proxy_class = get_module_proxy_class(module)
    if hasattr(module, "__path__"):
        return _PackageDefinition(
            underlying=module,
            proxy_class=proxy_class,
            get_module_proxy_class=get_module_proxy_class,
        )
    return _NamespaceDefinition(underlying=module, proxy_class=proxy_class)


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
    via :class:`InstanceProxy` or :meth:`StaticProxy.__call__`.

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

    Eager resources are evaluated immediately when the proxy is accessed,
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


def mount(
    namespace: ModuleType | _NamespaceDefinition,
) -> StaticProxy:
    """
    Resolves a Proxy from the given object using the provided lexical scope.

    :param namespace: Module or namespace definition (decorated with @scope) to resolve resources from.
    :return: An instance of the cls type with resolved mixins.

    Example::

        root = mount(MyNamespace)

    .. todo:: Phase 2: Pass ``symbol`` and ``base_symbols``
              when creating ``ChildMixin``.
    """
    lexical_scope: LexicalScope = ()
    symbol_table: SymbolTable = ChainMapSentinel.EMPTY
    root_proxy_class: type[StaticProxy] = CachedProxy

    def get_module_proxy_class(_module: ModuleType) -> type[StaticProxy]:
        return CachedProxy

    namespace_definition: _MixinDefinition
    if isinstance(namespace, _NamespaceDefinition):
        namespace_definition = namespace
    elif isinstance(namespace, ModuleType):
        namespace_definition = _parse_package(
            namespace,
            get_module_proxy_class=get_module_proxy_class,
        )
    else:
        assert_never(namespace)

    per_namespace_symbol_table = _extend_symbol_table_jit(
        outer=symbol_table,
        names=namespace_definition.__iter__(),
    )
    symbol = _MixinSymbol(
        name="__root__",
        proxy_definition=namespace_definition,
        symbol_table=per_namespace_symbol_table,
    )

    root_mixin = RootMixin(
        symbol=symbol,
    )
    return root_proxy_class(
        mixins={root_mixin: lexical_scope},
        mixin=root_mixin,
    )


def _make_jit_getter(name: str, depth: int) -> Callable[[LexicalScope], "Node"]:
    """Create a factory that retrieves a resource from lexical scope using JIT-compiled attribute access."""
    # lambda lexical_scope: lexical_scope[index].{name}
    lambda_node = ast.Lambda(
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="lexical_scope")],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=ast.Attribute(
            value=ast.Subscript(
                value=ast.Name(id="lexical_scope", ctx=ast.Load()),
                slice=ast.Constant(value=depth),
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


def _extend_symbol_table_jit(
    outer: SymbolTable,
    names: Iterable[str],
) -> SymbolTable:
    """Extend symbol table by adding a new layer that uses _SimpleSymbol instances."""
    if outer is ChainMapSentinel.EMPTY:
        new_symbols: dict[str, _Symbol] = {
            name: _SimpleSymbol(_depth=0, _resource_name=name) for name in names
        }
        return ChainMap(new_symbols)
    else:
        depth = len(outer.maps)
        new_symbols = {
            name: _SimpleSymbol(_depth=depth, _resource_name=name) for name in names
        }
        return outer.new_child(new_symbols)


def _resolve_dependencies_jit(
    symbol_table: SymbolTable,
    function: Callable[P, T],
    name: str,
) -> Callable[[LexicalScope], T]:
    """
    Resolve dependencies for a function using JIT-compiled AST.

    The first parameter of the function is treated as a :class:`Proxy` if it is
    positional-only. All other parameters are resolved from the symbol table.

    Special case: when param_name == name, uses outer symbol table to
    avoid self-dependency, mimicking pytest fixture behavior.

    :param symbol_table: A mapping from resource names to their resolution functions.
    :param function: The function for which to resolve dependencies.
    :param name: The name of the resource being resolved.
    :return: A wrapper function that takes a lexical scope (where the last element
             is the current proxy) and returns the result of the original function.
    """
    sig = signature(function)
    params = tuple(sig.parameters.values())

    if not params:
        return lambda _ls: function()  # type: ignore

    has_proxy = False
    p0 = params[0]
    first_param_in_symbol_table = (
        symbol_table is not ChainMapSentinel.EMPTY and p0.name in symbol_table
    )
    if (p0.kind == p0.POSITIONAL_ONLY) or (
        p0.kind == p0.POSITIONAL_OR_KEYWORD and not first_param_in_symbol_table
    ):
        has_proxy = True
        kw_params = params[1:]
    else:
        kw_params = params

    # Create keyword arguments for the call:
    # For same-name parameters (param_name == name), look up from outer symbol table
    # to avoid self-dependency. For other parameters, resolve from symbol_table.
    keywords = []
    for p in kw_params:
        if p.name == name:
            # Same-name dependency: look up from outer symbol table
            # Generates: symbol_table.parents[p.name].getter(lexical_scope)
            value_expr = ast.Call(
                func=ast.Attribute(
                    value=ast.Subscript(
                        value=ast.Attribute(
                            value=ast.Name(id="symbol_table", ctx=ast.Load()),
                            attr="parents",
                            ctx=ast.Load(),
                        ),
                        slice=ast.Constant(value=p.name),
                        ctx=ast.Load(),
                    ),
                    attr="getter",
                    ctx=ast.Load(),
                ),
                args=[ast.Name(id="lexical_scope", ctx=ast.Load())],
                keywords=[],
            )
        else:
            # Normal dependency: resolve from symbol_table
            # Generates: symbol_table[p.name].getter(lexical_scope)
            value_expr = ast.Call(
                func=ast.Attribute(
                    value=ast.Subscript(
                        value=ast.Name(id="symbol_table", ctx=ast.Load()),
                        slice=ast.Constant(value=p.name),
                        ctx=ast.Load(),
                    ),
                    attr="getter",
                    ctx=ast.Load(),
                ),
                args=[ast.Name(id="lexical_scope", ctx=ast.Load())],
                keywords=[],
            )
        keywords.append(ast.keyword(arg=p.name, value=value_expr))

    call_node = ast.Call(
        func=ast.Name(id="function", ctx=ast.Load()),
        args=(
            [
                ast.Subscript(
                    value=ast.Name(id="lexical_scope", ctx=ast.Load()),
                    slice=ast.Constant(value=-1),
                    ctx=ast.Load(),
                )
            ]
            if has_proxy
            else []
        ),
        keywords=keywords,
    )

    lambda_node = ast.Lambda(
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="lexical_scope")],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=call_node,
    )

    module_node = ast.Expression(body=lambda_node)
    ast.fix_missing_locations(module_node)
    code = compile(
        module_node, filename="<mixinject__resolve_dependencies_jit>", mode="eval"
    )

    return eval(
        code,
        {
            "function": function,
            "symbol_table": symbol_table,
        },
    )


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class AbsoluteReference(Generic[T]):
    """
    An absolute reference to a resource starting from the root scope.
    """

    path: Final[tuple[T, ...]]


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

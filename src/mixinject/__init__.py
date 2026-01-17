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
       def counter(counter: int) -> int:  # parameter resolved from parent
           return counter + 1

2. **@patch returning endo** (Patcher, endo receives base value from Merger)::

       @patch
       def counter() -> Callable[[int], int]:
           return lambda counter: counter + 1  # endo argument is base value

The key difference:

- ``@resource`` with same-name parameter creates a **new Merger** that shadows the
  outer definition. The parameter is resolved at compile-time from the parent scope's
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

    # Create an empty Proxy and inject values
    proxy = CachedProxy(_mixins=frozenset([]), _reversed_path=EmptyInternedLinkedList.INSTANCE)
    new_proxy = proxy(setting="value", count=42)

    # Access injected values
    assert new_proxy.setting == "value"
    assert new_proxy.count == 42

Primary Use Case
----------------

The primary use of Proxy as Callable is to provide base values for parameter injection.
By using :meth:`Proxy.__call__` in an outer scope to inject parameter values, resources in
modules can access these values via symbol table lookup::

    # Provide base value in outer scope
    outer_proxy = CachedProxy(_mixins=frozenset([]), _reversed_path=EmptyInternedLinkedList.INSTANCE) \
        (db_config={"host": "localhost", "port": "5432"})

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

import ast
from enum import Enum, auto
import importlib
import os
import importlib.util
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
    override,
)
from weakref import WeakValueDictionary

from mixinject.interned_linked_list import (
    EmptyInternedLinkedList,
    InternedLinkedList,
    NonEmptyInternedLinkedList,
)

P = ParamSpec("P")
T = TypeVar("T")
TKey = TypeVar("TKey", bound=Hashable)

Resource = NewType("Resource", object)


class Proxy(Mapping[TKey, "Node"], ABC):
    """
    A Proxy represents resources available via attributes or keys.

    There are two types of proxies:

    - ``StaticProxy``: Represents class/module level static definitions.
      Contains mixins and supports ``__call__`` to create instances.
    - ``InstanceProxy``: Created via ``StaticProxy.__call__``.
      Stores kwargs directly and delegates to base proxy for other lookups.

    .. todo::
        我希望把Proxy/CachedProxy/WeakCachedProxy合并成一个类，按需提供ResourceConfig的26种组合行为。

        我希望可以通过新增的一些decorator提供 ResourceConfig 的配置。注意这个配置是静态的不依赖于 Proxy 和 Scope，且可能将来会被JitCache编译进字节码里。
        ```
        @dataclass
        class BuilderDefinition:
            bind_lexical_scope: Callable[[LexicalScope, str], Callable[[Proxy, ResourceConfig], Merger | Patcher]]
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
    def mixins(self) -> frozenset["Mixin[TKey]"]:
        """The mixins that provide resources for this proxy."""
        ...

    @property
    @abstractmethod
    def reversed_path(self) -> "InternedLinkedList[TKey] | InstanceReversedPath[TKey]":
        """The reversed path from root to this proxy."""
        ...

    def __getitem__(self, key: TKey) -> "Node":
        def generate_resource() -> Iterator[Merger | Patcher]:
            for mixin in self.mixins:
                try:
                    factory_or_patch = mixin[key]
                except KeyError:
                    continue
                yield factory_or_patch(self)

        return _evaluate_resource(resource_generator=generate_resource)

    def __getattr__(self, key: str) -> "Node":
        try:
            return self[key]  # type: ignore[arg-type]
        except KeyError as e:
            raise AttributeError(name=key, obj=self) from e

    def __iter__(self) -> Iterator[TKey]:
        visited: set[TKey] = set()
        for mixin in self.mixins:
            for key in mixin:
                if key not in visited:
                    visited.add(key)
                    yield key

    def __len__(self) -> int:
        keys: set[TKey] = set()
        for mixin in self.mixins:
            keys.update(mixin)
        return len(keys)

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
class StaticProxy(Proxy[str], ABC):
    """
    A static proxy representing class/module level definitions.

    StaticProxy stores mixins directly and supports ``__call__`` to create
    InstanceProxy with additional kwargs.
    """

    _mixins: Final[frozenset["Mixin[str]"]]
    _reversed_path: Final[InternedLinkedList[str]]

    @property
    @override
    def mixins(self) -> frozenset["Mixin[str]"]:
        return self._mixins

    @property
    @override
    def reversed_path(self) -> InternedLinkedList[str]:
        return self._reversed_path

    def __call__(self, **kwargs: object) -> "InstanceProxy":
        return InstanceProxy(
            base_proxy=self,
            kwargs=kwargs,
        )


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class InstanceReversedPath(Generic[TKey]):
    """
    A wrapper for reversed path in InstanceProxy.

    This distinguishes the reversed path of an InstanceProxy from its base StaticProxy,
    allowing the path to be different for identity purposes.
    """

    base_reversed_path: Final[InternedLinkedList[TKey]]


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class InstanceProxy(Proxy[str]):
    """
    An instance proxy created via StaticProxy.__call__.

    InstanceProxy stores kwargs directly and checks them first during lookup,
    then delegates to the base proxy for other resources.
    """

    base_proxy: Final[StaticProxy]
    kwargs: Final[Mapping[str, object]]

    @property
    @override
    def mixins(self) -> frozenset["Mixin[str]"]:
        return self.base_proxy.mixins

    @property
    @override
    def reversed_path(self) -> InstanceReversedPath[str]:
        return InstanceReversedPath(base_reversed_path=self.base_proxy.reversed_path)

    @override
    def __getitem__(self, key: str) -> "Node":
        if key in self.kwargs:
            value = self.kwargs[key]

            def generate_resource() -> Iterator[Merger | Patcher]:
                # Yield the kwargs value as a Merger
                yield _EndofunctionMerger(base_value=cast(Resource, value))
                # Also collect any Patchers from mixins
                for mixin in self.mixins:
                    try:
                        factory_or_patch = mixin[key]
                    except KeyError:
                        continue
                    yield factory_or_patch(self)

            return _evaluate_resource(resource_generator=generate_resource)
        return super(InstanceProxy, self).__getitem__(key)

    @override
    def __iter__(self) -> Iterator[str]:
        yield from self.kwargs
        for key in super(InstanceProxy, self).__iter__():
            if key not in self.kwargs:
                yield key

    @override
    def __len__(self) -> int:
        base_keys: set[str] = set()
        for mixin in self.mixins:
            base_keys.update(mixin)
        return len(base_keys | set(self.kwargs))

    def __call__(self, **kwargs: object) -> "InstanceProxy":
        merged_kwargs: Mapping[str, object] = {**self.kwargs, **kwargs}
        return InstanceProxy(
            base_proxy=self.base_proxy,
            kwargs=merged_kwargs,
        )


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class CachedProxy(StaticProxy):
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


class SymbolTableSentinel(Enum):
    ROOT = auto()
    """
    A sentinel value representing the root symbol table when no scope is provided. This is a workaround for Python's quirk where a ChainMap always has at least one mapping. e.g. `len(ChainMap().maps)` is 1, not 0.
    """


SymbolTable: TypeAlias = (
    ChainMap[str, Callable[[LexicalScope], "Node"]] | Literal[SymbolTableSentinel.ROOT]
)
"""
A mapping from resource names to functions that take a lexical scope and return a Node.

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


class Mixin(Mapping[TKey, Callable[["Proxy[TKey]"], Merger | Patcher]], Hashable, ABC):
    """
    Abstract base class for mixins.
    Mixins are mappings from resource names to factory functions.
    They must compare by identity to allow storage in sets.
    """

    def __hash__(self) -> int:
        return hash(id(self))

    def __eq__(self, other: object) -> bool:
        return self is other


@dataclass(kw_only=True, slots=True, frozen=True, weakref_slot=True)
class _JitCache(Mapping[str, Callable[[LexicalScope], Merger | Patcher]]):
    """
    Mapping that caches resolve_symbols results for definitions in a namespace.

    .. todo:: Also compiles the proxy class into Python bytecode.
    """

    proxy_definition: Final["_ProxyDefinition"]
    symbol_table: Final[SymbolTable]
    cache: Final[dict[str, Callable[[LexicalScope], Merger | Patcher]]] = field(
        default_factory=dict
    )

    @property
    def underlying(self) -> object:
        return self.proxy_definition.underlying

    def __getitem__(self, key: str) -> Callable[[LexicalScope], Merger | Patcher]:
        if key in self.cache:
            return self.cache[key]
        try:
            val = getattr(self.proxy_definition.underlying, key)
        except AttributeError as e:
            raise KeyError(key) from e
        if not isinstance(val, Definition):
            raise KeyError(key)
        resolved = val.resolve_symbols(self.symbol_table, key)
        self.cache[key] = resolved
        return resolved

    def __iter__(self) -> Iterator[str]:
        return self.proxy_definition.generate_keys()

    def __len__(self) -> int:
        return sum(1 for _ in self)


@dataclass(frozen=True, kw_only=True, slots=True, eq=False)
class _NamespaceMixin(Mixin[str]):
    """Mixin that lazily resolves definitions from a NamespaceDefinition."""

    jit_cache: Final[_JitCache]
    lexical_scope: Final[LexicalScope]

    def __getitem__(self, key: str, /) -> Callable[[Proxy[str]], Merger | Patcher]:
        resolved_function = self.jit_cache[key]

        def bind_proxy(proxy: Proxy[str]) -> Merger | Patcher:
            inner_lexical_scope: LexicalScope = (*self.lexical_scope, proxy)
            return resolved_function(inner_lexical_scope)

        return bind_proxy

    def __iter__(self) -> Iterator[str]:
        return iter(self.jit_cache)

    def __len__(self) -> int:
        return len(self.jit_cache)


@dataclass(frozen=True, kw_only=True, slots=True, eq=False)
class _PackageMixin(_NamespaceMixin):
    """Mixin that lazily resolves definitions including submodules."""

    get_module_proxy_class: Callable[[ModuleType], type[StaticProxy]]

    @override
    def __getitem__(self, key: str, /) -> Callable[[Proxy[str]], Merger | Patcher]:
        # 1. Try parent implementation (attributes that are Definition)
        try:
            return super(_PackageMixin, self).__getitem__(key)
        except KeyError:
            pass

        # 2. Try submodule
        underlying = self.jit_cache.underlying
        full_name = f"{underlying.__name__}.{key}"  # type: ignore[union-attr]
        try:
            spec = importlib.util.find_spec(full_name)
        except ImportError as e:
            raise KeyError(key) from e

        if spec is None:
            raise KeyError(key)

        submod = importlib.import_module(full_name)
        # Create definition for submodule (lazy)
        submod_definition: "_ProxyDefinition"
        if hasattr(submod, "__path__"):
            submod_definition = _PackageDefinition(
                underlying=submod,
                proxy_class=self.get_module_proxy_class(submod),
                get_module_proxy_class=self.get_module_proxy_class,
            )
        else:
            submod_definition = _NamespaceDefinition(
                underlying=submod,
                proxy_class=self.get_module_proxy_class(submod),
            )
        resolved_function = submod_definition.resolve_symbols(
            self.jit_cache.symbol_table, key
        )

        def bind_proxy(proxy: Proxy[str]) -> Merger | Patcher:
            inner_lexical_scope: LexicalScope = (*self.lexical_scope, proxy)
            return resolved_function(inner_lexical_scope)

        return bind_proxy


def _evaluate_resource(
    resource_generator: Callable[[], Iterator[Merger | Patcher]],
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
        self, symbol_table: "SymbolTable", resource_name: str, /
    ) -> Callable[[LexicalScope], Merger | Patcher]:
        """
        Resolve symbols in the definition and return a function that takes a lexical scope
        and returns a Merger or Patcher.
        """
        raise NotImplementedError()


class MergerDefinition(Definition, Generic[TPatch_contra, TResult_co]):

    @abstractmethod
    def resolve_symbols(
        self, symbol_table: "SymbolTable", resource_name: str, /
    ) -> Callable[[LexicalScope], Merger]:
        raise NotImplementedError()


class PatcherDefinition(Definition, Generic[TPatch_co]):
    @abstractmethod
    def resolve_symbols(
        self, symbol_table: "SymbolTable", resource_name: str, /
    ) -> Callable[[LexicalScope], Patcher]:
        raise NotImplementedError()


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _MergerDefinition(MergerDefinition[TPatch_contra, TResult_co]):
    """Definition for merge decorator."""

    function: Callable[..., Callable[[Iterator[TPatch_contra]], TResult_co]]

    @override
    def resolve_symbols(
        self, symbol_table: "SymbolTable", resource_name: str, /
    ) -> Callable[[LexicalScope], Merger[TPatch_contra, TResult_co]]:
        jit_compiled_function = _resolve_dependencies_jit(
            symbol_table=symbol_table,
            function=self.function,
            resource_name=resource_name,
        )

        def resolve_lexical_scope(
            lexical_scope: LexicalScope,
        ) -> Merger[TPatch_contra, TResult_co]:
            aggregation_function = jit_compiled_function(lexical_scope)
            return FunctionMerger(aggregation_function=aggregation_function)

        return resolve_lexical_scope


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _ResourceDefinition(
    Generic[TResult], MergerDefinition[Callable[[TResult], TResult], TResult]
):
    """Definition for resource decorator."""

    function: Callable[..., TResult]

    @override
    def resolve_symbols(
        self, symbol_table: "SymbolTable", resource_name: str, /
    ) -> Callable[[LexicalScope], Merger[Callable[[TResult], TResult], TResult]]:
        jit_compiled_function = _resolve_dependencies_jit(
            symbol_table=symbol_table,
            function=self.function,
            resource_name=resource_name,
        )

        def resolve_lexical_scope(
            lexical_scope: LexicalScope,
        ) -> Merger[Callable[[TResult], TResult], TResult]:
            base_value = jit_compiled_function(lexical_scope)
            return _EndofunctionMerger(base_value=base_value)

        return resolve_lexical_scope


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _SinglePatchDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patch decorator (single patch)."""

    function: Callable[..., TPatch_co]

    @override
    def resolve_symbols(
        self, symbol_table: "SymbolTable", resource_name: str, /
    ) -> Callable[[LexicalScope], Patcher[TPatch_co]]:
        jit_compiled_function = _resolve_dependencies_jit(
            symbol_table=symbol_table,
            function=self.function,
            resource_name=resource_name,
        )

        def resolve_lexical_scope(lexical_scope: LexicalScope) -> Patcher[TPatch_co]:
            def patch_generator() -> Iterator[TPatch_co]:
                yield jit_compiled_function(lexical_scope)

            return FunctionPatcher(patch_generator=patch_generator)

        return resolve_lexical_scope


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _MultiplePatchDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patches decorator (multiple patches)."""

    function: Callable[..., Iterable[TPatch_co]]

    @override
    def resolve_symbols(
        self, symbol_table: "SymbolTable", resource_name: str, /
    ) -> Callable[[LexicalScope], Patcher[TPatch_co]]:
        jit_compiled_function = _resolve_dependencies_jit(
            symbol_table=symbol_table,
            function=self.function,
            resource_name=resource_name,
        )

        def resolve_lexical_scope(lexical_scope: LexicalScope) -> Patcher[TPatch_co]:
            def patch_generator() -> Iterator[TPatch_co]:
                return (yield from jit_compiled_function(lexical_scope))

            return FunctionPatcher(patch_generator=patch_generator)

        return resolve_lexical_scope


DefinitionMapping: TypeAlias = Mapping[
    str, Callable[[LexicalScope], Callable[[Proxy], Merger | Patcher]]
]


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _ProxySemigroup(Merger[Proxy, Proxy], Patcher[Proxy]):
    proxy_factory: Callable[[], Proxy]

    @override
    def create(self, patches: Iterator[Proxy]) -> Proxy:
        def all_proxies() -> Iterator[Proxy]:
            yield self.proxy_factory()
            return (yield from patches)

        proxies_tuple = tuple(all_proxies())
        assert proxies_tuple, "Expected at least one proxy from factory"

        winner_class = _calculate_most_derived_class(*(type(p) for p in proxies_tuple))

        def generate_all_mixins() -> Iterator[Mixin]:
            for proxy in proxies_tuple:
                yield from proxy.mixins

        return winner_class(
            _mixins=frozenset(generate_all_mixins()),
            _reversed_path=EmptyInternedLinkedList.INSTANCE,
        )

    @override
    def __iter__(self) -> Iterator[Proxy]:
        yield self.proxy_factory()


def _resolve_resource_reference(
    reference: "ResourceReference[str]",
    lexical_scope: LexicalScope,
) -> Proxy:
    """
    Resolve a ResourceReference to a Proxy using the given lexical scope.

    For RelativeReference:
        - Navigate up `levels_up` levels from the innermost proxy
        - Then navigate down through `parts` by accessing attributes

    For AbsoluteReference:
        - Start from the root (outermost proxy)
        - Navigate down through `parts` by accessing attributes
    """
    match reference:
        case RelativeReference(levels_up=levels_up, parts=parts):
            if levels_up > len(lexical_scope):
                raise ValueError(
                    f"Cannot navigate {levels_up} levels up from scope of depth {len(lexical_scope)}"
                )
            # Navigate up: levels_up=0 means innermost (last), levels_up=1 means parent, etc.
            scope_index = len(lexical_scope) - 1 - levels_up
            current: Proxy | Resource = lexical_scope[scope_index]
        case AbsoluteReference(parts=parts):
            if not lexical_scope:
                raise ValueError("Cannot resolve absolute reference with empty lexical scope")
            current = lexical_scope[0]
        case _ as unreachable:
            assert_never(unreachable)

    # Navigate through parts
    for part in parts:
        resolved = current[part]
        if not isinstance(resolved, Proxy):
            raise TypeError(
                f"Expected Proxy while resolving reference, got {type(resolved)} at part '{part}'"
            )
        current = resolved

    if not isinstance(current, Proxy):
        raise TypeError(f"Final resolved value is not a Proxy: {type(current)}")
    return current


@dataclass(frozen=True, kw_only=True)
class _ProxyDefinition(MergerDefinition[Proxy, Proxy], PatcherDefinition[Proxy]):
    proxy_class: type[StaticProxy]
    underlying: object
    extend: tuple["ResourceReference[str]", ...] = ()

    def generate_keys(self) -> Iterator[str]:
        for name in dir(self.underlying):
            try:
                val = getattr(self.underlying, name)
            except AttributeError:
                continue
            if isinstance(val, Definition):
                yield name

    @abstractmethod
    def create_mixin(
        self, lexical_scope: LexicalScope, symbol_table: SymbolTable
    ) -> Mixin:
        """
        Create a Mixin for this ProxyDefinition given the lexical scope and symbol table.
        Must be implemented by subclasses.
        """
        raise NotImplementedError()

    def resolve_symbols(
        self, symbol_table: SymbolTable, resource_name: str, /
    ) -> Callable[[LexicalScope], _ProxySemigroup]:
        inner_symbol_table: SymbolTable = _extend_symbol_table_jit(
            outer=symbol_table, names=self.generate_keys()
        )

        def resolve_lexical_scope(
            lexical_scope: LexicalScope,
        ) -> _ProxySemigroup:
            def proxy_factory() -> Proxy[str]:
                parent_reversed_path: InternedLinkedList[str] = (
                    lexical_scope[-1].reversed_path if lexical_scope else EmptyInternedLinkedList.INSTANCE
                )

                def generate_all_mixins() -> Iterator[Mixin[str]]:
                    # Include mixin from this definition
                    yield self.create_mixin(
                        lexical_scope=lexical_scope,
                        symbol_table=inner_symbol_table,
                    )
                    # Include mixins from extended proxies
                    for reference in self.extend:
                        extended_proxy = _resolve_resource_reference(
                            reference=reference,
                            lexical_scope=lexical_scope,
                        )
                        yield from extended_proxy.mixins

                return self.proxy_class(
                    _mixins=frozenset(generate_all_mixins()),
                    _reversed_path=NonEmptyInternedLinkedList(
                        head=resource_name,
                        tail=parent_reversed_path,
                    ),
                )

            return _ProxySemigroup(proxy_factory=proxy_factory)

        return resolve_lexical_scope


@dataclass(frozen=True, kw_only=True)
class _NamespaceDefinition(_ProxyDefinition):
    """
    A definition that creates a Proxy from an object's attributes.
    Implements lazy evaluation via resolve_symbols.
    """

    def create_mixin(
        self, lexical_scope: LexicalScope, symbol_table: SymbolTable
    ) -> Mixin:
        return _NamespaceMixin(
            jit_cache=_JitCache(
                proxy_definition=self,
                symbol_table=symbol_table,
            ),
            lexical_scope=lexical_scope,
        )


@dataclass(frozen=True, kw_only=True)
class _PackageDefinition(_ProxyDefinition):
    """A definition for packages that discovers submodules via pkgutil."""

    get_module_proxy_class: Callable[[ModuleType], type[StaticProxy]]
    underlying: ModuleType

    def generate_keys(self) -> Iterator[str]:
        yield from super(_PackageDefinition, self).generate_keys()

        for mod_info in pkgutil.iter_modules(self.underlying.__path__):
            yield mod_info.name

    def create_mixin(
        self, lexical_scope: LexicalScope, symbol_table: SymbolTable
    ) -> Mixin:
        return _PackageMixin(
            jit_cache=_JitCache(
                proxy_definition=self,
                symbol_table=symbol_table,
            ),
            lexical_scope=lexical_scope,
            get_module_proxy_class=self.get_module_proxy_class,
        )


def _parse_namespace(
    namespace: object, symbol_table: SymbolTable, proxy_class: type[StaticProxy]
) -> _NamespaceDefinition:
    """
    Parses an object into a NamespaceDefinition.

    Only attributes explicitly decorated with @resource, @patch, @patch_many, or @merge are included.
    Nested classes are NOT recursively parsed unless they are decorated with @scope.

    IMPORTANT: Bare callables (without decorators) are NOT automatically included.
    Users must explicitly mark all injectable definitions with appropriate decorators.
    """
    return _NamespaceDefinition(
        underlying=namespace,
        proxy_class=proxy_class,
    )


def scope(
    *,
    proxy_class: type[StaticProxy] = CachedProxy,
    extend: Iterable["ResourceReference[str]"] = (),
) -> Callable[[type], _NamespaceDefinition]:
    """
    Decorator that converts a class into a NamespaceDefinition.
    Nested classes MUST be decorated with @scope() to be included as sub-scopes.

    Note: Always use @scope() with parentheses, not @scope without parentheses.

    Args:
        proxy_class: The Proxy subclass to use for this scope.
        extend: ResourceReferences to other scopes whose mixins should be included.
            This allows composing scopes without explicit merge operations.

    Example - Using extend to inherit from another scope::

        @scope(extend=(
            RelativeReference(levels_up=1, parts=("Base",)),
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

    def wrapper(c: type) -> _NamespaceDefinition:
        return _NamespaceDefinition(
            underlying=c,
            proxy_class=proxy_class,
            extend=extend_tuple,
        )

    return wrapper


def _parse_package(
    module: ModuleType,
    get_module_proxy_class: Callable[[ModuleType], type[StaticProxy]],
    symbol_table: SymbolTable,
) -> _ProxyDefinition:
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

    Args:
        callable: A callable that may have parameters for dependency injection.
                 The return value is ignored.

    Returns:
        A PatcherDefinition that provides no patches.
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


def _parse(
    namespace: object,
    get_module_proxy_class: Callable[[ModuleType], type[StaticProxy]],
    symbol_table: SymbolTable,
    root_proxy_class: type[StaticProxy],
) -> _ProxyDefinition:
    if isinstance(namespace, ModuleType):
        return _parse_package(
            namespace,
            get_module_proxy_class=get_module_proxy_class,
            symbol_table=symbol_table,
        )
    else:
        return _parse_namespace(
            namespace, symbol_table=symbol_table, proxy_class=root_proxy_class
        )


def mount(
    *namespaces: object,
    lexical_scope: LexicalScope = (),
    symbol_table: SymbolTable = SymbolTableSentinel.ROOT,
    root_proxy_class: type[TProxy] = CachedProxy,
    get_module_proxy_class: Callable[[ModuleType], type[StaticProxy]] = lambda _: CachedProxy,
) -> TProxy:
    """
    Resolves a Proxy from the given objects using the provided lexical scope.

    Args:
        lexical_scope: The lexical scope chain for dependency resolution.
        *namespaces: Objects (modules, classes or instances) to resolve resources from.

    Returns:
        An instance of the cls type with resolved mixins.

    Examples:
        # Use default caching
        root = mount(MyNamespace)

        # Use weak reference caching
        root = mount(MyNamespace, root_proxy_class=WeakCachedScope)
    """

    namespace_definitions = tuple(
        _parse(
            namespace,
            get_module_proxy_class=get_module_proxy_class,
            symbol_table=SymbolTableSentinel.ROOT,
            root_proxy_class=root_proxy_class,
        )
        for namespace in namespaces
    )

    def make_mixin(namespace_definition: _ProxyDefinition) -> Mixin:
        per_namespace_symbol_table = _extend_symbol_table_jit(
            outer=symbol_table,
            names=namespace_definition.generate_keys(),
        )
        jit_cache = _JitCache(
            proxy_definition=namespace_definition,
            symbol_table=per_namespace_symbol_table,
        )
        if isinstance(namespace_definition, _PackageDefinition):
            return _PackageMixin(
                jit_cache=jit_cache,
                lexical_scope=lexical_scope,
                get_module_proxy_class=get_module_proxy_class,
            )
        else:
            return _NamespaceMixin(
                jit_cache=jit_cache,
                lexical_scope=lexical_scope,
            )

    return root_proxy_class(
        _mixins=frozenset(make_mixin(nd) for nd in namespace_definitions),
        _reversed_path=EmptyInternedLinkedList.INSTANCE,
    )


def _make_jit_factory(name: str, index: int) -> Callable[[LexicalScope], "Node"]:
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


def _extend_symbol_table_jit(
    outer: SymbolTable,
    names: Iterable[str],
) -> SymbolTable:
    """Extend symbol table by adding a new layer that uses JIT-compiled attribute-based factories."""
    if outer is SymbolTableSentinel.ROOT:
        return ChainMap({name: _make_jit_factory(name, 0) for name in names})
    else:
        index = len(outer.maps)
        return outer.new_child({name: _make_jit_factory(name, index) for name in names})


def _resolve_dependencies_jit(
    symbol_table: SymbolTable,
    function: Callable[P, T],
    resource_name: str,
) -> Callable[[LexicalScope], T]:
    """
    Resolve dependencies for a function using JIT-compiled AST.

    The first parameter of the function is treated as a :class:`Proxy` if it is
    positional-only. All other parameters are resolved from the symbol table.

    Special case: when param_name == resource_name, uses parent symbol table to
    avoid self-dependency, mimicking pytest fixture behavior.

    :param symbol_table: A mapping from resource names to their resolution functions.
    :param function: The function for which to resolve dependencies.
    :param resource_name: The name of the resource being resolved.
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
        symbol_table is not SymbolTableSentinel.ROOT and p0.name in symbol_table
    )
    if (p0.kind == p0.POSITIONAL_ONLY) or (
        p0.kind == p0.POSITIONAL_OR_KEYWORD and not first_param_in_symbol_table
    ):
        has_proxy = True
        kw_params = params[1:]
    else:
        kw_params = params

    # Create keyword arguments for the call:
    # For same-name parameters (param_name == resource_name), look up from parent symbol table
    # to avoid self-dependency. For other parameters, resolve from symbol_table.
    keywords = []
    for p in kw_params:
        if p.name == resource_name:
            # Same-name dependency: look up from parent symbol table
            value_expr = ast.Call(
                func=ast.Subscript(
                    value=ast.Attribute(
                        value=ast.Name(id="symbol_table", ctx=ast.Load()),
                        attr="parents",
                        ctx=ast.Load(),
                    ),
                    slice=ast.Constant(value=p.name),
                    ctx=ast.Load(),
                ),
                args=[ast.Name(id="lexical_scope", ctx=ast.Load())],
                keywords=[],
            )
        else:
            # Normal dependency: resolve from symbol_table
            value_expr = ast.Call(
                func=ast.Subscript(
                    value=ast.Name(id="symbol_table", ctx=ast.Load()),
                    slice=ast.Constant(value=p.name),
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

    parts: Final[tuple[T, ...]]


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class RelativeReference(Generic[T]):
    """
    A reference to a resource relative to the current lexical scope.

    This is used to refer to resources in parent scopes.
    """

    levels_up: Final[int]
    """
    Number of levels to go up in the lexical scope.
    """

    parts: Final[tuple[T, ...]]


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
        RelativeReference(levels_up=1, parts=('foo', 'bar'))
        >>> resource_reference_from_pure_path(PurePath("../../config"))
        RelativeReference(levels_up=2, parts=('config',))
        >>> resource_reference_from_pure_path(PurePath("/absolute/path"))
        AbsoluteReference(parts=('absolute', 'path'))
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
        return AbsoluteReference(parts=path_parts)

    all_parts = path.parts

    if all_parts == (os.curdir,):
        return RelativeReference(levels_up=0, parts=())

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

    return RelativeReference(levels_up=levels_up, parts=tuple(remaining_parts))

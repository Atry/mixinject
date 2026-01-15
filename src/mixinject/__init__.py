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
    :func:`patches`, or :func:`aggregator`.

**Proxy**
    An object that contains resources, accessed via attribute access (``.`` operator).
    Proxies can be nested to form hierarchical structures, analogous to a filesystem directory
    hierarchy. See :class:`Proxy`.

**Lexical Scope**
    The lookup chain for resolving resources, scanning from inner to outer layers.
    See :data:`LexicalScope`.

**Endo Function**
    A function of type ``Callable[[T], T]`` that transforms a value of type ``T`` into another
    value of the same type. See :data:`Endo`.

Core Design Principle: Explicit Decorator Marking
==================================================

All injectable definitions **MUST** be explicitly marked with one of these decorators:

- :func:`resource`: Creates a base resource that can be modified by patches
- :func:`patch`: Provides a single modification to an existing resource
- :func:`patches`: Provides multiple modifications to an existing resource
- :func:`aggregator`: Defines custom aggregation strategy for patches
- :func:`parameter`: Declares a parameter placeholder (syntactic sugar for empty :func:`patches`)

Bare callables (functions without decorators) are **NOT** automatically injected.
This explicit-only design makes dependency injection predictable and self-documenting.

Example::

    from mixinject import resource, patch, resolve

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

    root = resolve(...)
    root.greeting  # "Hello!"
    root.ignored_function  # AttributeError: 'CachedProxy' object has no attribute 'ignored_function'

Union Filesystem Analogy
========================

If we make an analogy to union filesystems:

- :class:`Proxy` objects are like directory objects
- Resources are like files
- Modules, packages, callables, and :class:`ScopeDefinition` are filesystem definitions before mounting
- The compiled result (from :func:`resolve`) is a concrete :class:`Proxy` that implements resource access

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

Same-Name Dependency (pytest-fixture Semantics)
------------------------------------------------

When a parameter name matches the resource name, it skips the current :class:`Proxy` and
looks for the same-named resource in outer scopes. This implements pytest fixture's
same-name dependency semantics::

    @resource
    def my_callable(my_callable: float) -> float:
        return my_callable + 1.0

This skips the current :class:`Proxy` and searches the lexical scope chain for the parent
:class:`Proxy`'s definition of ``my_callable``, allowing you to access and modify outer
definitions.

Merging and Composition
========================

Module and Package Merging
---------------------------

When merging modules and packages, mixinject uses an algorithm similar to
https://github.com/atry/mixin and https://github.com/mxmlnkn/ratarmount/pull/163.

Same-Named Callable Merging Rules
----------------------------------

When merging N same-named callables:

- Exactly **N-1** callables must be decorated with :func:`patch` or :func:`patches`
- Exactly **1** callable must be decorated with :func:`resource` or :func:`aggregator`
- Otherwise, a ``ValueError`` is raised

Union Mounting at Entry Point
------------------------------

At the framework entry point (:func:`resolve`), users can pass multiple packages, modules,
or objects, which are union-mounted into a unified root :class:`Proxy`, similar to
https://github.com/mxmlnkn/ratarmount/pull/163.

Endo-Only Resources as Parameters (Best Practice)
==================================================

Concept
-------

A resource can be defined **solely** by :func:`patch` or :func:`patches` decorators,
without a base definition from :func:`resource` or :func:`aggregator`. This **endo-only resource**
is essentially a "parameter" that allows other resources to depend on it, while the parameter's
final value comes from injection from an outer scope.

Identity Function Pattern
--------------------------

Endo-only patches are typically **identity functions** (``lambda x: x``), performing no
transformation. The key purpose is to **register the resource name in the lexical scope**,
allowing other resources to find it via lexical scope lookup.

**Recommended:** Use the :func:`parameter` decorator as syntactic sugar instead of writing
identity functions manually. It makes the intent clearer and reduces boilerplate.

When an endo-only resource is accessed, the system:

1. Looks up the resource name in the lexical scope
2. Finds the base value injected from outer scope via :class:`KeywordArgumentMixin`
3. Applies all endo-only patches (usually identity functions, so the value doesn't change)
4. Passes the final value to resources that depend on it

Example
-------

Using the recommended :func:`parameter` decorator::

    # config.py
    from mixinject import parameter, resource
    from typing import Dict

    @parameter
    def settings(): ...

    @resource
    def connection_string(settings: Dict[str, str]) -> str:
        \"\"\"Depends on parameter injected from outer scope.\"\"\"
        return f"{settings.get('host', 'localhost')}:{settings.get('port', '5432')}"

    # main.py
    from mixinject import resolve

    # Inject base value using Proxy.__call__
    root = resolve(config)(settings={"host": "db.example.com", "port": "3306"})
    assert root.connection_string == "db.example.com:3306"

Alternatively, using the identity function pattern (more verbose)::

    # config.py
    from mixinject import patch, resource
    from typing import Callable, Dict

    @patch
    def settings() -> Callable[[Dict[str, str]], Dict[str, str]]:
        \"\"\"Endo-only resource: identity function, no transformation.

        Exists solely to register 'settings' in the lexical scope.
        \"\"\"
        return lambda cfg: cfg  # identity function

    @resource
    def connection_string(settings: Dict[str, str]) -> str:
        \"\"\"Depends on endo-only resource as parameter.\"\"\"
        return f"{settings.get('host', 'localhost')}:{settings.get('port', '5432')}"

    # main.py
    from mixinject import resolve

    root = resolve(config)(settings={"host": "db.example.com", "port": "3306"})
    assert root.connection_string == "db.example.com:3306"

Key Advantages
--------------

**Lexical scope registration**
    Even without a base implementation, endo-only patches register the resource name,
    making it findable in the lexical scope.

**Flexible injection**
    Base values can be injected at runtime via outer scope's :class:`KeywordArgumentMixin`.

**Module decoupling**
    Modules don't need to know concrete resource values, only declare their existence.

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
containing all original mixins plus new values provided via kwargs (as :class:`KeywordArgumentMixin`).

Example::

    # Create an empty Proxy and inject values
    proxy = CachedProxy(mixins=frozenset([]))
    new_proxy = proxy(setting="value", count=42)

    # Access injected values
    assert new_proxy.setting == "value"
    assert new_proxy.count == 42

Primary Use Case
----------------

The primary use of Proxy as Callable is to provide base values for **endo-only resources**.
By using :meth:`Proxy.__call__` in an outer scope to inject parameter values, resources in
modules can access these values via same-named parameter lookup::

    # Provide base value in outer scope
    outer_proxy = CachedProxy(mixins=frozenset([])) \\
        (db_config={"host": "localhost", "port": "5432"})

    def outer_scope() -> Iterator[Proxy]:
        yield outer_proxy

    # Resources in modules can obtain this value via same-named parameter
    class Database:
        @resource
        def db_config(db_config: dict) -> dict:
            \"\"\"Same-name parameter: looks up from lexical scope.\"\"\"
            return db_config

Callables can be used not only to define resources but also to define and transform Proxy objects.
"""

import ast
import importlib
import importlib.util
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import reduce
from inspect import signature
from types import ModuleType
from typing import (
    Any,
    AsyncContextManager,
    Awaitable,
    Callable,
    ChainMap,
    Concatenate,
    ContextManager,
    Hashable,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    NewType,
    ParamSpec,
    Self,
    TypeAlias,
    TypeVar,
    cast,
    overload,
    override,
)
from warnings import deprecated
from weakref import WeakValueDictionary

P = ParamSpec("P")
T = TypeVar("T")

Resource = NewType("Resource", object)


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class Proxy(Mapping[str, "Node"], ABC):
    """
    A Proxy represents resources available via attributes or keys.

    .. todo::
        我希望把Proxy/CachedProxy/WeakCachedProxy合并成一个类，按需提供ResourceConfig的24种组合行为。

        我希望可以通过新增的一些decorator提供 ResourceConfig 的配置。注意这个配置是静态的不依赖于 Proxy 和 Scope，也就是说需要放在 Definition里，并且 Mixin 有办法查询到
        ```
        class Mixin:
            @abstractmethod
            def configure(self, previous: ResourceConfig) -> ResourceConfig: ... # forward call to definition
            ...
        class Definition:
            @abstractmethod
            def bind_lexical_scope(...): ...
            @abstractmethod
            def configure(self, previous: ResourceConfig) -> ResourceConfig: ...
        ```


        用同一套Builder/Patcher接口来处理context manager/async，但是`TResult`的类型取决于ResourceConfig，可能是Awaitable/ContextManager/AsyncContextManager，或是直接的同步类型。`@resource`的`TPatch`的类型也取决于ResourceConfig，可能是`Endo`/`ContextManagerEndo`/`AsyncEndo`/`AsyncContextManagerEndo`。也就是说同一套Builder/Patcher接口可以处理同步/异步/上下文管理器的情况，

    """

    mixins: frozenset["Mixin"]

    def __getitem__(self, key: str) -> "Node":
        def generate_resource() -> Iterator[Builder | Patcher]:
            for mixins in self.mixins:
                try:
                    factory_or_patch = mixins[key]
                except KeyError:
                    continue
                yield factory_or_patch(self)

        return _evaluate_resource(resource_generator=generate_resource)

    def __getattr__(self, key: str) -> "Node":
        try:
            return self[key]
        except KeyError as e:
            raise AttributeError(name=key, obj=self) from e

    def __iter__(self) -> Iterator[str]:
        visited: set[str] = set()
        for mixins in self.mixins:
            for key in mixins:
                if key not in visited:
                    visited.add(key)
                    yield key

    def __len__(self) -> int:
        keys: set[str] = set()
        for mixins in self.mixins:
            keys.update(mixins)
        return len(keys)

    @override
    def __dir__(self):
        """
        .. note:: This method uses the two-arg super() as a workaround for https://github.com/python/cpython/pull/124455
        """
        return (*self, *super(Proxy, self).__dir__())

    def __call__(self, **kwargs: object) -> Self:
        return type(self)(mixins=self.mixins | {_KeywordArgumentMixin(kwargs=kwargs)})


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class CachedProxy(Proxy):
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


def merge_proxies(proxies: Iterable[Proxy]) -> Proxy:
    """
    Merge multiple proxies into a single proxy.
    The resulting proxy's class is the most derived class among the input proxies.
    The resulting proxy's mixins are the union of all input proxies' mixins.
    """
    proxies_tuple = tuple(proxies)
    if not proxies_tuple:
        raise ValueError("No proxies to merge")

    winner_class = _calculate_most_derived_class(*(type(p) for p in proxies_tuple))

    def generate_all_mixins() -> Iterator[Mixin]:
        for p in proxies_tuple:
            yield from p.mixins

    return winner_class(mixins=frozenset(generate_all_mixins()))


LexicalScope: TypeAlias = Callable[[], Iterator[Proxy]]
"""
A generator function that yields proxies representing the lexical scope, starting from the innermost proxy to the outermost proxy.
"""


def _loop_up(lexical_scope: LexicalScope, name: str) -> "Node":
    """
    Look up a resource by name in the lexical scope chain.
    Returns the first found value, searching from innermost to outermost scope.
    """
    for proxy in lexical_scope():
        try:
            return proxy[name]
        except KeyError:
            continue
    raise KeyError(name)


Node: TypeAlias = Resource | Proxy
TPatch_co = TypeVar("TPatch_co", covariant=True)
TPatch_contra = TypeVar("TPatch_contra", contravariant=True)
TResult_co = TypeVar("TResult_co", covariant=True)


class Builder(Generic[TPatch_contra, TResult_co], ABC):
    @abstractmethod
    def create(self, patches: Iterator[TPatch_contra]) -> TResult_co: ...


class Patcher(Iterable[TPatch_co], ABC):
    """
    An Patcher provides extra data to be applied to a Node created by a ``Builder``.
    """


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FunctionPatcher(Patcher[TPatch_co]):
    patch_generator: Callable[[], Iterator[TPatch_co]]

    def __iter__(self) -> Iterator[TPatch_co]:
        return self.patch_generator()


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FunctionBuilder(Builder[TPatch_contra, TResult_co]):
    """Builder that applies custom aggregation function to patches."""

    aggregation_function: Callable[[Iterator[TPatch_contra]], TResult_co]

    @override
    def create(self, patches: Iterator[TPatch_contra]) -> TResult_co:
        return self.aggregation_function(patches)


TResult = TypeVar("TResult")
TProxy = TypeVar("TProxy", bound=Proxy)


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _EndoBuilder(Generic[TResult], Builder[Callable[[TResult], TResult], TResult]):
    """Builder that applies patches as endofunctions via reduce."""

    base_value: TResult

    @override
    def create(self, patches: Iterator[Callable[[TResult], TResult]]) -> TResult:
        return reduce(lambda acc, endo: endo(acc), patches, self.base_value)


class Mixin(Mapping[str, Callable[[Proxy], Builder | Patcher]], Hashable, ABC):
    """
    Abstract base class for mixins.
    Mixins are mappings from resource names to factory functions.
    They must compare by identity to allow storage in sets.
    """

    def __hash__(self) -> int:
        return hash(id(self))

    def __eq__(self, other: object) -> bool:
        return self is other


def _evaluate_resource(
    resource_generator: Callable[[], Iterator[Builder | Patcher]],
) -> Node:
    """
    Evaluate a resource by selecting a Builder and applying Patches.

    Algorithm for selecting the Builder:
    1. If there is exactly one item that is a Builder but NOT a Patch (pure Builder),
       it is selected as the Builder. All other items (including those that are both)
       are treated as Patches.
    2. If there are multiple pure Builders, a ValueError is raised.
    3. If there are no pure Builders, but there are items that are both Builder and Patch:
       One is arbitrarily selected as the Builder, and the rest are treated as Patches.
       (This assumes the semantics of these items satisfy commutativity).
    4. If there are no Builders (pure or dual), a NotImplementedError is raised.
    """
    items = list(resource_generator())
    if not items:
        raise KeyError("No resource found")

    pure_builders: list[Builder] = []
    pure_patches: list[Patcher] = []
    dual_items: list[Builder] = []  # Typed as Builder, but are also Patch

    for item in items:
        is_builder = isinstance(item, Builder)
        is_patch = isinstance(item, Patcher)

        if is_builder and not is_patch:
            pure_builders.append(item)
        elif is_builder and is_patch:
            dual_items.append(item)  # type: ignore
        elif is_patch:
            pure_patches.append(item)

    selected_builder: Builder
    patches_to_apply: list[Patcher]

    if len(pure_builders) == 1:
        selected_builder = pure_builders[0]
        # Dual items are treated as patches here
        patches_to_apply = cast(list[Patcher], dual_items) + pure_patches
    elif len(pure_builders) > 1:
        raise ValueError("Multiple Factory definitions provided")
    else:
        # No pure builders
        if not dual_items:
            raise NotImplementedError("No Factory definition provided")

        # Pick one dual item as builder
        selected_builder = dual_items[0]
        # Remaining dual items are patches
        patches_to_apply = cast(list[Patcher], dual_items[1:]) + pure_patches

    # Flatten the patches
    flat_patches = (
        patch_content
        for patch_container in patches_to_apply
        for patch_content in patch_container
    )

    return selected_builder.create(flat_patches)


class Definition(ABC):
    @deprecated("Use resolve_symbols() instead")
    @abstractmethod
    def bind_lexical_scope(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Builder | Patcher]: ...

    def resolve_symbols(
        self, symbol_table: "SymbolTable", resource_name: str, /
    ) -> Callable[[LexicalScope], Callable[[Proxy], Builder | Patcher]]:
        """
        The fallback implementation that calls the legacy bind_lexical_scope method, should be overridden in subclasses to avoid the deprecated behavior.
        """
        return lambda lexical_scope: self.bind_lexical_scope(
            lexical_scope, resource_name
        )


class BuilderDefinition(Definition, Generic[TPatch_contra, TResult_co]):
    @abstractmethod
    def bind_lexical_scope(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Builder]: ...


class PatcherDefinition(Definition, Generic[TPatch_co]):
    @abstractmethod
    def bind_lexical_scope(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Patcher]: ...


def _resolve_dependencies(
    function: Callable[..., Any],
    resource_name: str,
    outer_lexical_scope: LexicalScope,
    proxy: Proxy,
) -> Mapping[str, Any]:
    """
    Resolve dependencies for a callable based on its parameter names.

    Special case: when param_name == resource_name, uses outer lexical scope (not current proxy).
    This implements pytest-fixture-like same-name dependency injection semantics.

    Normal case: param_name != resource_name looks in current proxy first, then falls back to outer lexical scope.
    """

    def resolve_param(param_name: str) -> Any:
        """
        Resolve a single parameter by name.
        1. If param_name == resource_name, look up in outer lexical scope to avoid self-dependency, mimicking pytest fixture behavior.
        2. Otherwise, try to get from current proxy, falling back to outer lexical scope if not found.
        """
        if param_name == resource_name:
            # pytest fixture-like behavior to not recursively depend on itself
            return _loop_up(outer_lexical_scope, param_name)
        try:
            return proxy[param_name]
        except KeyError:
            return _loop_up(outer_lexical_scope, param_name)

    sig = signature(function)
    return {param_name: resolve_param(param_name) for param_name in sig.parameters}


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _AggregatorDefinition(BuilderDefinition[TPatch_contra, TResult_co]):
    """Definition for aggregator decorator."""

    function: Callable[..., Callable[[Iterator[TPatch_contra]], TResult_co]]

    @override
    def bind_lexical_scope(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Builder[TPatch_contra, TResult_co]]:
        def bind_proxy(proxy: Proxy) -> Builder[TPatch_contra, TResult_co]:
            dependencies = _resolve_dependencies(
                self.function, resource_name, outer_lexical_scope, proxy
            )
            return FunctionBuilder(aggregation_function=self.function(**dependencies))

        return bind_proxy


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _ResourceDefinition(
    Generic[TResult], BuilderDefinition[Callable[[TResult], TResult], TResult]
):
    """Definition for resource decorator."""

    function: Callable[..., TResult]

    @override
    def bind_lexical_scope(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Builder[Callable[[TResult], TResult], TResult]]:
        def bind_proxy(proxy: Proxy) -> Builder[Callable[[TResult], TResult], TResult]:
            resolved_args = _resolve_dependencies(
                self.function, resource_name, outer_lexical_scope, proxy
            )
            base_value = self.function(**resolved_args)
            return _EndoBuilder(base_value=base_value)

        return bind_proxy


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _SinglePatchDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patch decorator (single patch)."""

    function: Callable[..., TPatch_co]

    @override
    def bind_lexical_scope(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Patcher[TPatch_co]]:
        def bind_proxy(proxy: Proxy) -> Patcher[TPatch_co]:
            def patch_generator() -> Iterator[TPatch_co]:
                resolved_args = _resolve_dependencies(
                    self.function, resource_name, outer_lexical_scope, proxy
                )
                yield self.function(**resolved_args)

            return FunctionPatcher(patch_generator=patch_generator)

        return bind_proxy


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _MultiplePatchDefinition(PatcherDefinition[TPatch_co]):
    """Definition for patches decorator (multiple patches)."""

    function: Callable[..., Iterable[TPatch_co]]

    @override
    def bind_lexical_scope(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Patcher[TPatch_co]]:
        def bind_proxy(proxy: Proxy) -> Patcher[TPatch_co]:
            def patch_generator() -> Iterator[TPatch_co]:
                resolved_args = _resolve_dependencies(
                    self.function, resource_name, outer_lexical_scope, proxy
                )
                yield from self.function(**resolved_args)

            return FunctionPatcher(patch_generator=patch_generator)

        return bind_proxy


DefinitionMapping: TypeAlias = Mapping[str, Definition]


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _ProxyBuilderPatcher(Builder[Proxy, Proxy], Patcher[Proxy]):
    definitions: DefinitionMapping
    lexical_scope: LexicalScope
    proxy_class: type[Proxy]

    def own_proxy(self):
        return self.proxy_class(
            mixins=frozenset(
                (
                    _BoundMixin(
                        lexical_scope=self.lexical_scope, definitions=self.definitions
                    ),
                )
            )
        )

    @override
    def create(self, patches: Iterator[Proxy]) -> Proxy:
        def all_proxies():
            yield self.own_proxy()
            yield from patches

        return merge_proxies(all_proxies())

    @override
    def __iter__(self) -> Iterator[Proxy]:
        yield self.own_proxy()


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class _ScopeDefinition(BuilderDefinition[Proxy, Proxy], PatcherDefinition[Proxy]):
    """Definition that creates a Proxy from nested ScopeDefinition (lazy evaluation)."""

    definitions: DefinitionMapping
    proxy_class: type[Proxy]

    @override
    def bind_lexical_scope(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], _ProxyBuilderPatcher]:
        def bind_proxy(proxy: Proxy) -> _ProxyBuilderPatcher:
            def inner_lexical_scope() -> Iterator[Proxy]:
                yield proxy
                yield from outer_lexical_scope()

            return _ProxyBuilderPatcher(
                definitions=self.definitions,
                lexical_scope=inner_lexical_scope,
                proxy_class=self.proxy_class,
            )

        return bind_proxy


@dataclass(frozen=True, kw_only=True)
class _NamespaceDefinition(DefinitionMapping, Generic[T]):
    """
    A lazy mapping that parses definitions from an object's attributes on access.
    Implements call-by-name semantics using dir() and getattr().
    """

    underlying: T

    def __getitem__(self, key: str) -> Definition:
        try:
            val = getattr(self.underlying, key)
        except AttributeError as e:
            raise KeyError(key) from e

        if isinstance(val, Definition):
            return val
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        for name in dir(self.underlying):
            try:
                val = getattr(self.underlying, name)
            except AttributeError:
                continue
            if isinstance(val, Definition):
                yield name

    def __len__(self) -> int:
        return sum(1 for _ in self)


@dataclass(frozen=True, kw_only=True)
class _PackageDefinition(_NamespaceDefinition[ModuleType]):
    """A lazy mapping that discovers submodules via pkgutil and imports them on access."""

    get_module_proxy_class: Callable[[ModuleType], type[Proxy]]

    @override
    def __getitem__(self, key: str) -> Definition:
        # 1. Try to get attribute from module (using super - finds Definition)
        try:
            return super().__getitem__(key)
        except KeyError:
            pass

        # 2. Try to find in submodules (if package)
        full_name = f"{self.underlying.__name__}.{key}"  # type: ignore
        try:
            spec = importlib.util.find_spec(full_name)
        except ImportError as e:
            raise KeyError(key) from e

        if spec is None:
            raise KeyError(key)

        submod = importlib.import_module(full_name)
        return _ScopeDefinition(
            definitions=_parse_package(
                submod, get_module_proxy_class=self.get_module_proxy_class
            ),
            proxy_class=self.get_module_proxy_class(submod),
        )

    @override
    def __iter__(self) -> Iterator[str]:
        # 1. Yield attributes that are Definitions (using super)
        yield from super().__iter__()

        # 2. Yield submodule names
        for mod_info in pkgutil.iter_modules(self.underlying.__path__):  # type: ignore
            yield mod_info.name

    @override
    def __contains__(self, key: object) -> bool:
        if super().__contains__(key):
            return True
        if not isinstance(key, str):
            return False

        full_name = f"{self.underlying.__name__}.{key}"  # type: ignore
        try:
            return importlib.util.find_spec(full_name) is not None
        except ImportError:
            return False


def _parse_namespace(namespace: object) -> DefinitionMapping:
    """
    Parses an object into a ScopeDefinition.

    Only attributes explicitly decorated with @resource, @patch, @patches, or @aggregator are included.
    Nested classes are NOT recursively parsed unless they are decorated with @scope.

    IMPORTANT: Bare callables (without decorators) are NOT automatically included.
    Users must explicitly mark all injectable definitions with appropriate decorators.
    """
    return _NamespaceDefinition(underlying=namespace)


def scope(
    cls: type | None = None, /, *, proxy_class: type[Proxy] = CachedProxy
) -> _ScopeDefinition | Callable[[type], _ScopeDefinition]:
    """
    Decorator that converts a class into a ScopeProxyDefinition.
    Nested classes MUST be decorated with @scope to be included as sub-scopes.
    """

    def wrapper(c: type) -> _ScopeDefinition:
        return _ScopeDefinition(
            definitions=_parse_namespace(c), proxy_class=proxy_class
        )

    if cls is None:
        return wrapper
    return wrapper(cls)


def _parse_package(
    module: ModuleType, get_module_proxy_class: Callable[[ModuleType], type[Proxy]]
) -> DefinitionMapping:
    """
    Parses a module into a ScopeDefinition.

    Only module-level attributes explicitly decorated with @resource, @patch, @patches, or @aggregator are included.
    Nested modules and packages are recursively parsed with lazy loading.

    IMPORTANT: Bare callables (without decorators) are NOT automatically included.
    Users must explicitly mark all injectable definitions with appropriate decorators.

    For packages (modules with __path__), uses pkgutil.iter_modules to discover submodules
    and importlib.import_module to lazily import them when accessed.
    """
    if hasattr(module, "__path__"):
        return _PackageDefinition(
            underlying=module, get_module_proxy_class=get_module_proxy_class
        )
    return _NamespaceDefinition(underlying=module)


Endo = Callable[[TResult], TResult]
ContextManagerEndo = Callable[[TResult], "ContextManager[TResult]"]
AsyncEndo = Callable[[TResult], Awaitable[TResult]]
AsyncContextManagerEndo = Callable[[TResult], "AsyncContextManager[TResult]"]


def aggregator(
    callable: Callable[..., Callable[[Iterator[TPatch_contra]], TResult_co]],
) -> BuilderDefinition[TPatch_contra, TResult_co]:
    """
    A decorator that converts a callable into a builder definition with a custom aggregation strategy for patches.

    Example:

    The following example defines an aggregator that deduplicates strings from multiple patches into a frozenset.
        # In branch0.py:

        from mixinject import aggregator
        @aggregator
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

        # In branch0.py:
        @aggregator
        def union_mount_point():
            return lambda mixins: CachedProxy(frozenset(mixins))

        # In branch1.py:
        @patch
        def union_mount_point():
            return KeywordArgumentMixin(kwargs={"foo": "foo"})

        # In branch2.py:
        @dataclass
        class Mixin2:
            def bar(self, foo: str) -> str:
                return f"{foo}_bar"

        # Still in branch2.py:
        @patches
        def union_mount_point():
            return resolve(Mixin2()).mixins

        # In main.py:
        import branch0
        import branch1
        import branch2
        import branch3
        root = resolve(branch0, branch1, branch2, branch3)
        root.deduplicated_tags  # frozenset(("tag1", "tag2_dependency_value"))
        root.union_mount_point.foo  # "foo"
        root.union_mount_point.bar  # "foo_bar"
        root.union_mount_point.mixins  # frozenset of all mixins from branch0, branch1, branch2, branch3


    Suppose we have an `branch3/example_module.py` defined in the same directory, and we can resolve it in `branch3/__init__.py`:

        # In __init__.py:
        @patches
        def union_mount_point(example_module: Proxy):
            return example_module.mixins
    """
    return _AggregatorDefinition(function=callable)


def patch(
    callable: Callable[..., TPatch_co],
) -> PatcherDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return _SinglePatchDefinition(function=callable)


def patches(
    callable: Callable[..., Iterable[TPatch_co]],
) -> PatcherDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return _MultiplePatchDefinition(function=callable)


def parameter(callable: Callable[..., Any]) -> PatcherDefinition[Any]:
    """
    A decorator that marks a callable as a parameter placeholder.

    This is syntactic sugar equivalent to :func:`patches` returning an empty collection.
    It registers the resource name in the lexical scope without providing any patches,
    making it clear that the value should come from injection from an outer lexical scope
    via :class:`KeywordArgumentMixin` or :meth:`Proxy.__call__`.

    The decorated callable may have parameters for dependency injection, which will be
    resolved from the lexical scope when the resource is accessed. However, the callable's
    return value is ignored.

    Example::

        @parameter
        def database_url(): ...

        # Equivalent to:
        @patches
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
) -> BuilderDefinition[Endo[TResult], TResult]:
    """
    A decorator that converts a callable into a builder definition that treats patches as endofunctions.

    It's a syntactic sugar for using ``aggregator`` with a standard endofunction application strategy.

    Example:
    The following example defines a resource that can be modified by patches.
        from mixinject import resource, patch
        @resource
        def greeting() -> str:
            return "Hello"


        @patch
        def enthusiastic_greeting() -> Endo[str]:
            return lambda original: original + "!!!"

    Alternatively, ``greeting`` can be defined with an explicit aggregator:
        from mixinject import aggregator
        @aggregator
        def greeting() -> Callable[[Iterator[Endo[str]]], str]:
            return lambda endos: reduce(
                (lambda original, endo: endo(original)),
                endos,
                "Hello"
            )
    """
    return _ResourceDefinition(function=callable)


@dataclass(frozen=True, kw_only=True, slots=True, eq=False)
class _BoundMixin(Mixin):
    """
    A Mixin that binds a lexical scope to a set of definitions.
    """

    lexical_scope: LexicalScope
    definitions: DefinitionMapping

    def __getitem__(self, key: str, /) -> Callable[[Proxy], Builder | Patcher]:
        definition = self.definitions[key]
        return definition.bind_lexical_scope(self.lexical_scope, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self.definitions)

    def __len__(self) -> int:
        return len(self.definitions)


def _parse(
    namespace: object, get_module_proxy_class: Callable[[ModuleType], type[Proxy]]
) -> DefinitionMapping:
    if isinstance(namespace, ModuleType):
        return _parse_package(namespace, get_module_proxy_class=get_module_proxy_class)
    else:
        return _parse_namespace(namespace)


def resolve(
    *namespaces: object,
    lexical_scope: LexicalScope = ().__iter__,
    root_proxy_class: type[TProxy] = CachedProxy,
    get_module_proxy_class: Callable[[ModuleType], type[Proxy]] = lambda _: CachedProxy,
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
        root = resolve(().__iter__, MyNamespace)

        # Use weak reference caching
        root = resolve(().__iter__, MyNamespace, cls=WeakCachedScope)
    """

    mixins = (
        _BoundMixin(
            lexical_scope=lexical_scope,
            definitions=_parse(
                namespace, get_module_proxy_class=get_module_proxy_class
            ),
        )
        for namespace in namespaces
    )

    return root_proxy_class(mixins=frozenset(mixins))


@dataclass(frozen=True, kw_only=True, slots=True, eq=False)
class _KeywordArgumentMixin(Mixin):
    kwargs: Mapping[str, object]

    def __getitem__(self, key: str) -> Callable[[Proxy], Builder]:
        if key not in self.kwargs:
            raise KeyError(key)
        value = self.kwargs[key]

        def bind_proxy(proxy: Proxy) -> Builder[Any, Resource]:
            return _EndoBuilder(base_value=cast(Resource, value))

        return bind_proxy

    def __iter__(self) -> Iterator[str]:
        return iter(self.kwargs)

    def __len__(self) -> int:
        return len(self.kwargs)


SymbolTable: TypeAlias = ChainMap[str, Callable[[LexicalScope], Node]]
"""
A mapping from resource names to functions that take a lexical scope and return a Node.

.. note:: NEVER ever modify a SymbolTable in-place. Always create a new ChainMap layer to add new definitions.
"""


def _resolve_dependencies_kwargs(
    symbol_table: SymbolTable,
    function: Callable[P, T],
) -> Callable[[LexicalScope], T]:
    """
    Resolve dependencies for a function using standard keyword arguments.

    The first parameter of the function is treated as a :class:`Proxy` if it is
    positional-only, or if it is positional-or-keyword and its name is not present
    in the symbol table. All other parameters are resolved from the symbol table.

    This implementation uses a standard closure that constructs a dictionary of
    resolved dependencies and passes them to the function using ``**kwargs``.

    :param symbol_table: A mapping from resource names to their resolution functions.
    :param function: The function for which to resolve dependencies.
    :return: A wrapper function that takes a lexical scope (where the first element
             is the current proxy) and returns the result of the original function.
    """
    sig = signature(function)
    params = list(sig.parameters.values())

    has_proxy = False
    if params:
        p0 = params[0]
        if (p0.kind == p0.POSITIONAL_ONLY) or (
            p0.kind == p0.POSITIONAL_OR_KEYWORD and p0.name not in symbol_table
        ):
            has_proxy = True
            kw_params = params[1:]
        else:
            kw_params = params
    else:
        kw_params = []

    def resolved_function(lexical_scope: LexicalScope) -> T:
        kwargs = {
            param.name: symbol_table[param.name](lexical_scope) for param in kw_params
        }
        if has_proxy:
            return function(lexical_scope[0], **kwargs)  # type: ignore
        else:
            return function(**kwargs)  # type: ignore

    return resolved_function


def _resolve_dependencies_jit(
    symbol_table: SymbolTable,
    function: Callable[P, T],
) -> Callable[[LexicalScope], T]:
    """
    Resolve dependencies for a function using JIT-compiled AST.

    The first parameter of the function is treated as a :class:`Proxy` if it is
    positional-only, or if it is positional-or-keyword and its name is not present
    in the symbol table. All other parameters are resolved from the symbol table.

    This implementation generates a specialized lambda function using Python's
    AST module, which directly calls the dependency resolution functions. This
    can be more efficient than :func:`_resolve_dependencies_kwargs` as it avoids
    creating a dictionary for keyword arguments at each call.

    .. todo:: 需要实现pytest fixture风格的同名依赖注入语义，即当参数名与资源名相同时，从symbol_table.parents中获取符号，而不是从symbol_table本身获取。这需要给 _resolve_dependencies_jit 添加 resource_name 参数，并在生成的AST中实现相应的逻辑。

    :param symbol_table: A mapping from resource names to their resolution functions.
    :param function: The function for which to resolve dependencies.
    :return: A wrapper function that takes a lexical scope (where the first element
             is the current proxy) and returns the result of the original function.
    """
    sig = signature(function)
    params = list(sig.parameters.values())

    if not params:
        return lambda _ls: function()  # type: ignore

    has_proxy = False
    p0 = params[0]
    if (p0.kind == p0.POSITIONAL_ONLY) or (
        p0.kind == p0.POSITIONAL_OR_KEYWORD and p0.name not in symbol_table
    ):
        has_proxy = True
        kw_params = params[1:]
    else:
        kw_params = params

    # Create keyword arguments for the call: name=symbol_table['name'](lexical_scope)
    keywords = [
        ast.keyword(
            arg=p.name,
            value=ast.Call(
                func=ast.Subscript(
                    value=ast.Name(id="symbol_table", ctx=ast.Load()),
                    slice=ast.Constant(value=p.name),
                    ctx=ast.Load(),
                ),
                args=[ast.Name(id="lexical_scope", ctx=ast.Load())],
                keywords=[],
            ),
        )
        for p in kw_params
    ]

    call_node = ast.Call(
        func=ast.Name(id="function", ctx=ast.Load()),
        args=[
            ast.Subscript(
                value=ast.Name(id="lexical_scope", ctx=ast.Load()),
                slice=ast.Constant(value=0),
                ctx=ast.Load(),
            )
        ]
        if has_proxy
        else [],
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

    return eval(code, {"function": function, "symbol_table": symbol_table})

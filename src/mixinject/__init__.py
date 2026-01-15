"""
mixinject: A dependency injection framework with pytest-fixture-like semantics.

## Core Design Principle: Explicit Decorator Marking

All injectable definitions MUST be explicitly marked with one of these decorators:
- @resource: Creates a base resource that can be modified by patches
- @patch: Provides a single modification to an existing resource
- @patches: Provides multiple modifications to an existing resource
- @aggregator: Defines custom aggregation strategy for patches

Bare callables (functions without decorators) are NOT automatically injected.
This explicit-only design makes dependency injection predictable and self-documenting.

## Example

```python
from mixinject import resource, patch, resolve_root

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

root = resolve_root(...)
root.greeting  # "Hello!"
root.ignored_function  # AttributeError: 'CachedProxy' object has no attribute 'ignored_function'
```
"""

import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import reduce
from inspect import signature
from types import ModuleType
from typing import (
    Any,
    Callable,
    Collection,
    Hashable,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    NewType,
    Self,
    TypeAlias,
    TypeVar,
    cast,
    override,
)
from weakref import WeakValueDictionary

Resource = NewType("Resource", object)


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class Proxy(Mapping[str, "Node"], ABC):
    """
    A Proxy represents resources available via attributes or keys.
    """

    mixins: frozenset["Mixin"]

    def __getitem__(self, key: str) -> "Node":
        def generate_resource() -> Iterator[Builder | Patch]:
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

    def __call__(self, **kwargs: object) -> Self:
        return type(self)(mixins=self.mixins | {simple_mixin(**kwargs)})


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class CachedProxy(Proxy):
    _cache: MutableMapping[str, "Node"] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @override
    def __getitem__(self, key: str) -> "Node":
        if key not in self._cache:
            value = Proxy.__getitem__(self, key)
            self._cache[key] = value
            return value
        else:
            return self._cache[key]


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class WeakCachedScope(CachedProxy):
    _cache: MutableMapping[str, "Node"] = field(
        default_factory=WeakValueDictionary, init=False, repr=False, compare=False
    )


LexicalScope: TypeAlias = Callable[[], Iterator[Proxy]]
"""
A generator function that yields proxies representing the lexical scope, starting from the innermost proxy to the outermost proxy.
"""


def loop_up(lexical_scope: LexicalScope, name: str) -> "Node":
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


class Builder(ABC, Generic[TPatch_contra, TResult_co]):
    @abstractmethod
    def create(self, patches: Iterator[TPatch_contra]) -> TResult_co: ...


class Patch(Iterable[TPatch_co], ABC):
    """
    An Patch provides extra data to be applied to a Node created by a Factory.
    """


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FunctionPatch(Patch[TPatch_co]):
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
class EndoBuilder(Generic[TResult], Builder[Callable[[TResult], TResult], TResult]):
    """Builder that applies patches as endofunctions via reduce."""

    base_value: TResult

    @override
    def create(self, patches: Iterator[Callable[[TResult], TResult]]) -> TResult:
        return reduce(lambda acc, endo: endo(acc), patches, self.base_value)


class Mixin(Mapping[str, Callable[[Proxy], Builder | Patch]], Hashable, ABC):
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
    resource_generator: Callable[[], Iterator[Builder | Patch]],
) -> Node:
    factories = (
        maybe_factory
        for maybe_factory in resource_generator()
        if isinstance(maybe_factory, Builder)
    )
    try:
        factory = next(factories)
    except StopIteration:
        try:
            next(resource_generator())
        except StopIteration:
            raise KeyError("No resource found")
        else:
            raise NotImplementedError("No Factory definition provided")
    else:
        try:
            next(factories)
        except StopIteration:
            pass
        else:
            raise ValueError("Multiple Factory definitions provided")
        patchs = (
            patch
            for maybe_patch in resource_generator()
            if isinstance(maybe_patch, Patch)
            for patch in maybe_patch
        )
        return factory.create(patchs)


class BuilderDefinition(ABC, Generic[TPatch_contra, TResult_co]):
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Builder]: ...


class PatchDefinition(ABC, Generic[TPatch_co]):
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Patch]: ...


Definition: TypeAlias = BuilderDefinition | PatchDefinition
DefinitionMapping: TypeAlias = Mapping[str, Definition]


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
        if param_name == resource_name:
            return loop_up(outer_lexical_scope, param_name)
        try:
            return proxy[param_name]
        except KeyError:
            return loop_up(outer_lexical_scope, param_name)

    sig = signature(function)
    return {param_name: resolve_param(param_name) for param_name in sig.parameters}


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class AggregatorDefinition(BuilderDefinition[TPatch_contra, TResult_co]):
    """Definition for aggregator decorator."""

    function: Callable[..., Callable[[Iterator[TPatch_contra]], TResult_co]]

    @override
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Builder[TPatch_contra, TResult_co]]:
        def factory(proxy: Proxy) -> Builder[TPatch_contra, TResult_co]:
            resolved_args = _resolve_dependencies(
                self.function, resource_name, outer_lexical_scope, proxy
            )
            aggregation_fn = self.function(**resolved_args)
            return FunctionBuilder(aggregation_function=aggregation_fn)

        return factory


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class ResourceDefinition(
    Generic[TResult], BuilderDefinition[Callable[[TResult], TResult], TResult]
):
    """Definition for resource decorator."""

    function: Callable[..., TResult]

    @override
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Builder[Callable[[TResult], TResult], TResult]]:
        def factory(proxy: Proxy) -> Builder[Callable[[TResult], TResult], TResult]:
            resolved_args = _resolve_dependencies(
                self.function, resource_name, outer_lexical_scope, proxy
            )
            base_value = self.function(**resolved_args)
            return EndoBuilder(base_value=base_value)

        return factory


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class PatchDefinitionImpl(PatchDefinition[TPatch_co]):
    """Definition for patch decorator (single patch)."""

    function: Callable[..., TPatch_co]

    @override
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Patch[TPatch_co]]:
        def factory(proxy: Proxy) -> Patch[TPatch_co]:
            def patch_generator() -> Iterator[TPatch_co]:
                resolved_args = _resolve_dependencies(
                    self.function, resource_name, outer_lexical_scope, proxy
                )
                yield self.function(**resolved_args)

            return FunctionPatch(patch_generator=patch_generator)

        return factory


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class PatchesDefinitionImpl(PatchDefinition[TPatch_co]):
    """Definition for patches decorator (multiple patches)."""

    function: Callable[..., Collection[TPatch_co]]

    @override
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Patch[TPatch_co]]:
        def factory(proxy: Proxy) -> Patch[TPatch_co]:
            def patch_generator() -> Iterator[TPatch_co]:
                resolved_args = _resolve_dependencies(
                    self.function, resource_name, outer_lexical_scope, proxy
                )
                yield from self.function(**resolved_args)

            return FunctionPatch(patch_generator=patch_generator)

        return factory


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class ScopeDefinition(BuilderDefinition[Mixin, Proxy]):
    """Definition that creates a Proxy from nested ScopeDefinition (lazy evaluation)."""

    definitions: DefinitionMapping

    @override
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Builder[Mixin, Proxy]]:
        def factory(proxy: Proxy) -> Builder[Mixin, Proxy]:
            def create_proxy(patches: Iterator[Mixin]) -> Proxy:
                def inner_lexical_scope() -> Iterator[Proxy]:
                    yield proxy
                    yield from outer_lexical_scope()

                base_mixin = compile(inner_lexical_scope, self.definitions)
                all_mixins = frozenset((base_mixin, *patches))
                return CachedProxy(mixins=all_mixins)

            return FunctionBuilder(aggregation_function=create_proxy)

        return factory


@dataclass(frozen=True, kw_only=True, slots=True)
class LazySubmoduleMapping(Mapping[str, Definition]):
    """A lazy mapping that discovers submodules via pkgutil and imports them on access."""

    parent_module: ModuleType
    submodule_names: frozenset[str]
    direct_attrs: Mapping[str, Definition]

    def __getitem__(self, key: str) -> Definition:
        if key in self.direct_attrs:
            return self.direct_attrs[key]
        if key in self.submodule_names:
            full_name = f"{self.parent_module.__name__}.{key}"
            submod = importlib.import_module(full_name)
            return ScopeDefinition(definitions=parse_module(submod))
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(frozenset(self.direct_attrs.keys()) | self.submodule_names)

    def __len__(self) -> int:
        return len(frozenset(self.direct_attrs.keys()) | self.submodule_names)

    def __contains__(self, key: object) -> bool:
        return key in self.direct_attrs or key in self.submodule_names


def parse_object(namespace: object) -> DefinitionMapping:
    """
    Parses an object into a ScopeDefinition.

    Only attributes explicitly decorated with @resource, @patch, @patches, or @aggregator are included.
    Nested classes are NOT recursively parsed unless they are decorated with @scope.

    IMPORTANT: Bare callables (without decorators) are NOT automatically included.
    Users must explicitly mark all injectable definitions with appropriate decorators.
    """

    namespace_dict = (
        vars(namespace) if isinstance(namespace, type) else vars(type(namespace))
    )
    result: dict[str, Definition] = {}
    for name, attr in namespace_dict.items():
        if isinstance(attr, (BuilderDefinition, PatchDefinition)):
            result[name] = attr
    return result


def scope(cls: type) -> ScopeDefinition:
    """
    Decorator that converts a class into a ScopeProxyDefinition.
    Nested classes MUST be decorated with @scope to be included as sub-scopes.
    """
    return ScopeDefinition(definitions=parse_object(cls))


def parse_module(module: ModuleType) -> DefinitionMapping:
    """
    Parses a module into a ScopeDefinition.

    Only module-level attributes explicitly decorated with @resource, @patch, @patches, or @aggregator are included.
    Nested modules and packages are recursively parsed with lazy loading.

    IMPORTANT: Bare callables (without decorators) are NOT automatically included.
    Users must explicitly mark all injectable definitions with appropriate decorators.

    For packages (modules with __path__), uses pkgutil.iter_modules to discover submodules
    and importlib.import_module to lazily import them when accessed.
    """

    direct_attrs_dict: dict[str, Definition] = {}
    for name in dir(module):
        attr = getattr(module, name)
        if isinstance(attr, (BuilderDefinition, PatchDefinition)):
            direct_attrs_dict[name] = attr
        elif isinstance(attr, ModuleType):
            direct_attrs_dict[name] = ScopeDefinition(definitions=parse_module(attr))
    direct_attrs: Mapping[str, Definition] = direct_attrs_dict

    if hasattr(module, "__path__"):
        submodule_names = frozenset(
            mod_info.name for mod_info in pkgutil.iter_modules(module.__path__)
        )
        return LazySubmoduleMapping(
            parent_module=module,
            submodule_names=submodule_names,
            direct_attrs=direct_attrs,
        )

    return direct_attrs


Endo = Callable[[TResult], TResult]


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
            return simple_mixin(foo="foo")

        # In branch2.py:
        @dataclass
        class Mixin2:
            def bar(self, foo: str) -> str:
                return f"{foo}_bar"

        # Still in branch2.py:
        @patches
        def union_mount_point():
            return resolve_root(Mixin2()).mixins

        # In main.py:
        import branch0
        import branch1
        import branch2
        import branch3
        root = resolve_root(branch0, branch1, branch2, branch3)
        root.deduplicated_tags  # frozenset({"tag1", "tag2_dependency_value"})
        root.union_mount_point.foo  # "foo"
        root.union_mount_point.bar  # "foo_bar"
        root.union_mount_point.mixins  # frozenset of all mixins from branch0, branch1, branch2, branch3


    Suppose we have an `branch3/example_module.py` defined in the same directory, and we can resolve it in `branch3/__init__.py`:

        # In __init__.py:
        @patches
        def union_mount_point(example_module: Proxy):
            return example_module.mixins
    """
    return AggregatorDefinition(function=callable)


def patch(
    callable: Callable[..., TPatch_co],
) -> PatchDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return PatchDefinitionImpl(function=callable)


def patches(
    callable: Callable[..., Collection[TPatch_co]],
) -> PatchDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return PatchesDefinitionImpl(function=callable)


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
    return ResourceDefinition(function=callable)


@dataclass(frozen=True, kw_only=True, slots=True, eq=False)
class CompiledMixin(Mixin):
    lexical_scope: LexicalScope
    normalized_scope_definition: DefinitionMapping

    def __getitem__(self, key: str) -> Callable[[Proxy], Builder | Patch]:
        if key not in self.normalized_scope_definition:
            raise KeyError(key)
        definition = self.normalized_scope_definition[key]
        return definition(self.lexical_scope, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self.normalized_scope_definition)

    def __len__(self) -> int:
        return len(self.normalized_scope_definition)


def compile(
    lexical_scope: LexicalScope,
    normalized_scope_definition: DefinitionMapping,
) -> Mixin:
    return CompiledMixin(
        lexical_scope=lexical_scope,
        normalized_scope_definition=normalized_scope_definition,
    )


def parse(obj: object) -> DefinitionMapping:
    if isinstance(obj, ModuleType):
        return parse_module(obj)
    else:
        return parse_object(obj)


def resolve(
    lexical_scope: LexicalScope,
    /,
    *objects: object,
    cls: type[TProxy] = CachedProxy,
) -> TProxy:
    """
    Resolves a Proxy from the given objects using the provided lexical scope.

    Args:
        lexical_scope: The lexical scope chain for dependency resolution.
        *objects: Objects (classes or modules) to resolve resources from.
        cls: The Proxy class to instantiate. Defaults to CachedProxy.
             Can be customized to use different caching strategies (e.g., WeakCachedScope).

    Returns:
        An instance of the cls type with resolved mixins.

    Examples:
        # Use default caching
        root = resolve(().__iter__, MyNamespace)

        # Use weak reference caching
        root = resolve(().__iter__, MyNamespace, cls=WeakCachedScope)
    """

    mixins = frozenset(compile(lexical_scope, parse(obj)) for obj in objects)
    return cls(mixins=mixins)


def resolve_root(*objects: object, cls: type[TProxy] = CachedProxy) -> TProxy:
    """
    Resolves the root Proxy from the given objects using an empty lexical scope.

    Args:
        *objects: Objects (classes or modules) to resolve resources from.
        cls: The Proxy class to instantiate. Defaults to CachedProxy.
             Can be customized to use different caching strategies (e.g., WeakCachedScope).

    Returns:
        An instance of the cls type with resolved mixins.

    Examples:
        # Use default caching
        root = resolve_root(MyNamespace)

        # Use weak reference caching
        root = resolve_root(MyNamespace, cls=WeakCachedScope)

        # Use custom proxy subclass
        root = resolve_root(MyNamespace, cls=CustomProxy)
    """
    return resolve(().__iter__, *objects, cls=cls)


@dataclass(frozen=True, kw_only=True, slots=True, eq=False)
class KeywordArgumentMixin(Mixin):
    kwargs: Mapping[str, object]

    def __getitem__(self, key: str) -> Callable[[Proxy], Builder | Patch]:
        if key not in self.kwargs:
            raise KeyError(key)
        value = self.kwargs[key]

        def factory(proxy: Proxy) -> Builder[Any, Resource]:
            return EndoBuilder(base_value=cast(Resource, value))

        return factory

    def __iter__(self) -> Iterator[str]:
        return iter(self.kwargs)

    def __len__(self) -> int:
        return len(self.kwargs)


def simple_mixin(**kwargs: object) -> Mixin:
    return KeywordArgumentMixin(kwargs=kwargs)

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import reduce
from inspect import signature
from types import ModuleType
from typing import (
    Any,
    Callable,
    Collection,
    Dict,
    Generator,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    NewType,
    Protocol,
    Self,
    TypeAlias,
    TypeVar,
    cast,
    override,
)
from weakref import WeakValueDictionary

Resource = NewType("Resource", object)


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class Proxy(ABC):
    """
    A Proxy represents resources available via attributes or keys.
    """

    components: frozenset["Component"]

    def __getattr__(self, key: str) -> "Node":
        def generate_resource() -> Iterator[Builder | Patch]:
            for components in self.components:
                try:
                    factory_or_patch = components(key)
                except AttributeError:
                    continue
                yield factory_or_patch(self)

        return _evaluate_resource(resource_generator=generate_resource)


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class CachedProxy(Proxy):
    _cache: MutableMapping[str, "Node"] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @override
    def __getattr__(self, key: str) -> "Node":
        if key not in self._cache:
            value = Proxy.__getattr__(self, key)
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
            return getattr(proxy, name)
        except AttributeError:
            continue
    raise AttributeError(name)


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


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class EndoBuilder(Generic[TResult], Builder[Callable[[TResult], TResult], TResult]):
    """Builder that applies patches as endofunctions via reduce."""

    base_value: TResult

    @override
    def create(self, patches: Iterator[Callable[[TResult], TResult]]) -> TResult:
        return reduce(lambda acc, endo: endo(acc), patches, self.base_value)


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class SimpleBuilder(Builder[Any, Resource]):
    """Builder for simple static values."""

    value: Resource

    @override
    def create(self, patches: Iterator[Any]) -> Resource:
        for _ in patches:
            pass
        return self.value


Component: TypeAlias = Callable[[str], Callable[[Proxy], Builder | Patch]]


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
        raise KeyError("No Factory definition provided")
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


def _resolve_dependencies(
    callable_obj: Callable[..., Any],
    resource_name: str,
    outer_lexical_scope: LexicalScope,
    proxy: Proxy,
) -> Mapping[str, Any]:
    """
    Resolve dependencies for a callable based on its parameter names.

    Special case: when param_name == resource_name, uses outer lexical scope (not current proxy).
    This implements pytest-fixture-like same-name dependency injection semantics.
    """
    sig = signature(callable_obj)
    return {
        param_name: (
            loop_up(outer_lexical_scope, param_name)
            if param_name == resource_name
            else getattr(proxy, param_name)
        )
        for param_name in sig.parameters
    }


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class AggregatorDefinition(BuilderDefinition[TPatch_contra, TResult_co]):
    """Definition for aggregator decorator."""

    callable_obj: Callable[..., Callable[[Iterator[TPatch_contra]], TResult_co]]

    @override
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Builder[TPatch_contra, TResult_co]]:
        def factory(proxy: Proxy) -> Builder[TPatch_contra, TResult_co]:
            resolved_args = _resolve_dependencies(
                self.callable_obj, resource_name, outer_lexical_scope, proxy
            )
            aggregation_fn = self.callable_obj(**resolved_args)
            return FunctionBuilder(aggregation_function=aggregation_fn)

        return factory


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class ResourceDefinitionImpl(
    Generic[TResult], BuilderDefinition[Callable[[TResult], TResult], TResult]
):
    """Definition for resource decorator."""

    callable_obj: Callable[..., TResult]

    @override
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Builder[Callable[[TResult], TResult], TResult]]:
        def factory(proxy: Proxy) -> Builder[Callable[[TResult], TResult], TResult]:
            resolved_args = _resolve_dependencies(
                self.callable_obj, resource_name, outer_lexical_scope, proxy
            )
            base_value = self.callable_obj(**resolved_args)
            return EndoBuilder(base_value=base_value)

        return factory


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class PatchDefinitionImpl(PatchDefinition[TPatch_co]):
    """Definition for patch decorator (single patch)."""

    callable_obj: Callable[..., TPatch_co]

    @override
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Patch[TPatch_co]]:
        def factory(proxy: Proxy) -> Patch[TPatch_co]:
            def patch_generator() -> Iterator[TPatch_co]:
                resolved_args = _resolve_dependencies(
                    self.callable_obj, resource_name, outer_lexical_scope, proxy
                )
                yield self.callable_obj(**resolved_args)

            return FunctionPatch(patch_generator=patch_generator)

        return factory


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class PatchesDefinitionImpl(PatchDefinition[TPatch_co]):
    """Definition for patches decorator (multiple patches)."""

    callable_obj: Callable[..., Collection[TPatch_co]]

    @override
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Patch[TPatch_co]]:
        def factory(proxy: Proxy) -> Patch[TPatch_co]:
            def patch_generator() -> Iterator[TPatch_co]:
                resolved_args = _resolve_dependencies(
                    self.callable_obj, resource_name, outer_lexical_scope, proxy
                )
                yield from self.callable_obj(**resolved_args)

            return FunctionPatch(patch_generator=patch_generator)

        return factory


@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class ScopeProxyDefinition(BuilderDefinition[Component, Proxy]):
    """Definition that creates a Proxy from nested ScopeDefinition (lazy evaluation)."""

    scope_definition: "ScopeDefinition"

    @override
    def __call__(
        self, outer_lexical_scope: LexicalScope, resource_name: str, /
    ) -> Callable[[Proxy], Builder[Component, Proxy]]:
        def factory(proxy: Proxy) -> Builder[Component, Proxy]:
            def create_proxy(patches: Iterator[Component]) -> Proxy:
                def inner_lexical_scope() -> Iterator[Proxy]:
                    yield proxy
                    yield from outer_lexical_scope()

                normalized = normalize_scope(self.scope_definition)
                base_component = compile(inner_lexical_scope, normalized)
                all_components = frozenset((base_component, *patches))
                return CachedProxy(components=all_components)

            return FunctionBuilder(aggregation_function=create_proxy)

        return factory


ResourceDefinition: TypeAlias = BuilderDefinition | PatchDefinition
ScopeDefinition: TypeAlias = Mapping[str, "ResourceDefinition | ScopeDefinition"]


def parse_namespace(namespace: object) -> ScopeDefinition:
    """
    Parses an object into a ScopeDefinition.

    Each callable attribute of the object is converted into a ResourceDefinition via the `resource` decorator.
    Attributes that are already ResourceDefinitions are returned as-is.
    Nested classes are treated as sub-scopes.
    """

    def parse_attr(attr: object) -> ResourceDefinition | ScopeDefinition:
        if isinstance(attr, (BuilderDefinition, PatchDefinition)):
            return attr
        if isinstance(attr, type):
            return parse_namespace(attr)
        return resource(cast(Callable[..., Node], attr))

    namespace_dict = vars(namespace) if isinstance(namespace, type) else vars(type(namespace))
    return {
        name: parse_attr(attr)
        for name, attr in namespace_dict.items()
        if callable(attr) or isinstance(attr, (BuilderDefinition, PatchDefinition, type))
    }


def parse_module(module: ModuleType) -> ScopeDefinition:
    """
    Parses a module into a ScopeDefinition.

    This function behaves similarly to `parse_namespace`, but is specifically designed to handle nested modules and packages, which are converted into ``Definition``s of ``Proxy``.

    Nested modules are returned as lazy ScopeDefinitions (via parse_module recursion wrapped in a lambda),
    which will be converted to ScopeProxyDefinition during normalization.

    TODO: 需要用 pkgutil 和 importlib 处理嵌套 package 和 module
    """

    def parse_attr(attr: object) -> ResourceDefinition | ScopeDefinition:
        if isinstance(attr, (BuilderDefinition, PatchDefinition)):
            return attr
        if isinstance(attr, ModuleType):
            return parse_module(attr)
        return resource(cast(Callable[..., Node], attr))

    return {
        name: parse_attr(attr)
        for name in dir(module)
        for attr in (getattr(module, name),)
        if callable(attr) or isinstance(attr, ModuleType) or isinstance(attr, (BuilderDefinition, PatchDefinition))
    }


NormalizedScopeDefinition = Mapping[str, ResourceDefinition]


def normalize(definition: ResourceDefinition | ScopeDefinition) -> ResourceDefinition:
    """
    Normalizes a ResourceDefinition or ScopeDefinition by converting any nested ScopeDefinitions into ResourceDefinitions of Proxy.
    """
    if isinstance(definition, (BuilderDefinition, PatchDefinition)):
        return definition
    return ScopeProxyDefinition(scope_definition=definition)


def normalize_scope(scope_definition: ScopeDefinition) -> NormalizedScopeDefinition:
    """
    Normalizes a ScopeDefinition by converting any nested ScopeDefinitions into ResourceDefinitions of Proxy.
    """
    return {key: normalize(value) for key, value in scope_definition.items()}


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
            return lambda components: CachedProxy(frozenset(components))

        # In branch1.py:
        @patch
        def union_mount_point():
            return simple_component(foo="foo")

        # In branch2.py:
        @dataclass
        class Mixin2:
            def bar(self, foo: str) -> str:
                return f"{foo}_bar"

        # Still in branch2.py:
        @patches
        def union_mount_point():
            return resolve_root(Mixin2()).components

        # In main.py:
        import branch0
        import branch1
        import branch2
        import branch3
        root = resolve_root(branch0, branch1, branch2, branch3)
        root.deduplicated_tags  # frozenset({"tag1", "tag2_dependency_value"})
        root.union_mount_point.foo  # "foo"
        root.union_mount_point.bar  # "foo_bar"
        root.union_mount_point.components  # frozenset of all components from branch0, branch1, branch2, branch3


    Suppose we have an `branch3/example_module.py` defined in the same directory, and we can resolve it in `branch3/__init__.py`:

        # In __init__.py:
        @patches
        def union_mount_point(example_module: Proxy):
            return example_module.components
    """
    return AggregatorDefinition(callable_obj=callable)


def patch(
    callable: Callable[..., TPatch_co],
) -> PatchDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return PatchDefinitionImpl(callable_obj=callable)


def patches(
    callable: Callable[..., Collection[TPatch_co]],
) -> PatchDefinition[TPatch_co]:
    """
    A decorator that converts a callable into a patch definition.
    """
    return PatchesDefinitionImpl(callable_obj=callable)


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
    return ResourceDefinitionImpl(callable_obj=callable)


def compile(
    lexical_scope: LexicalScope,
    normalized_scope_definition: NormalizedScopeDefinition,
) -> Component:
    def component(name: str) -> Callable[[Proxy], Builder | Patch]:
        if name not in normalized_scope_definition:
            raise AttributeError(name)
        definition = normalized_scope_definition[name]
        return definition(lexical_scope, name)

    return component


def resolve(lexical_scope: LexicalScope, /, *objects: object) -> Proxy:
    def parse_object(obj: object) -> ScopeDefinition:
        if isinstance(obj, ModuleType):
            return parse_module(obj)
        return parse_namespace(obj)

    components = frozenset(
        compile(lexical_scope, normalize_scope(parse_object(obj)))
        for obj in objects
    )
    return CachedProxy(components=components)


def resolve_root(*objects: object) -> Proxy:
    """
    Resolves the root Proxy from the given objects.
    """
    return resolve(().__iter__, *objects)


def simple_component(**kwargs: object) -> Component:
    def component(name: str) -> Callable[[Proxy], Builder]:
        if name not in kwargs:
            raise AttributeError(name)
        value = kwargs[name]

        def factory(proxy: Proxy) -> Builder[Any, Resource]:
            return SimpleBuilder(value=cast(Resource, value))

        return factory

    return component

"""
Mixin and Scope implementation for proper is_public and is_eager support.

This module provides a cleaner architecture with:
- Single lazy evaluation level (at Mixin.evaluated only)
- Frozen Scope containers
- Proper circular dependency support via two-phase construction
- Correct is_public and is_eager semantics (private by default)

NOTE: This module does NOT include dynamic class generation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from functools import cached_property, reduce
from typing import (
    TYPE_CHECKING,
    Callable,
    Final,
    Generic,
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    TypeVar,
    final,
)

from overlay.language import HasDict, OuterSentinel


class KwargsSentinel(Enum):
    """Sentinel for distinguishing static scopes from instance scopes."""

    STATIC = auto()
    """No kwargs - this is a static scope (created via evaluate or nested scope access)."""


if TYPE_CHECKING:
    from overlay.language import (
        EndofunctionMergerSymbol,
        FunctionalMergerSymbol,
        MixinSymbol,
        MultiplePatcherSymbol,
        SinglePatcherSymbol,
    )


T = TypeVar("T")
TPatch_co = TypeVar("TPatch_co", covariant=True)
TPatch_contra = TypeVar("TPatch_contra", contravariant=True)
TResult_co = TypeVar("TResult_co", covariant=True)
TResult = TypeVar("TResult")



@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class Mixin(HasDict):
    """
    Lazy evaluation wrapper for resources and scopes.

    Mixin is mutable (NOT frozen) to support two-phase construction
    for circular dependencies within the same Scope.

    All lazy evaluation happens ONLY at Mixin.evaluated level.
    Dynamically decides whether to evaluate to a resource value or Scope.

    .. note::

       Does NOT inherit from Node/Mixin - completely separate hierarchy.
       Inherits from HasDict to support @cached_property with slots=True.

    .. todo:: Dynamic slots for sibling dependencies

       Currently sibling dependencies are stored in ``HasDict.__dict__`` via setattr.
       For better performance, future implementation should use ``make_dataclass``
       to dynamically generate Mixin subclasses with slots for each dependency.

       Example future design::

           DynamicMixin = make_dataclass(
               "DynamicMixin",
               [("foo", Mixin), ("bar", Mixin)],  # sibling dependency slots
               bases=(Mixin,),
               slots=True,
           )

    .. todo:: Nephew-uncle dependency support

       Currently sibling dependencies only contains sibling-to-sibling dependencies
       within the same scope. Nephew-uncle dependencies (where a nested scope's resource
       depends on its parent's sibling, i.e., an "uncle") are NOT supported.

       This limitation exists because we want lazy compilation for nested scopes (nephews).
       If we were to include nephew-uncle dependencies, we would need to eagerly analyze
       all nested scopes at construction time, defeating laziness.

       Example of unsupported pattern::

           @scope
           class Outer:
               @local
               @resource
               def uncle() -> str:  # Uncle is @local
                   return "uncle_value"

               @scope
               class Inner:
                   @resource
                   def nephew(uncle: str) -> str:  # Nephew depends on uncle
                       return f"got_{uncle}"  # ERROR: uncle is @local, not accessible

       Future solution: Add a ``@friend`` decorator that marks a scope for Ahead-Of-Time
       analysis. When applied, the scope's nested resources would be analyzed at
       construction time, allowing nephew-uncle dependencies to be wired.
       This would enable nephews to access uncle's @local resources.
    """

    symbol: Final["MixinSymbol"]

    outer: Final["Mixin | OuterSentinel"]
    """
    The outer Mixin (parent scope), or OuterSentinel.ROOT for root.

    To find parent scope dependencies:

    - Evaluate outer.evaluated to get the parent Scope
    - Then access the dependency from that Scope
    """

    kwargs: Final["Mapping[str, object] | KwargsSentinel"]
    """
    Keyword arguments for instance scope support.

    - KwargsSentinel.STATIC: This is a static scope (no instance kwargs)
    - Mapping[str, object]: This is an instance scope with the given kwargs

    Used by _evaluate_resource for PATCHER_ONLY resources to get base values.
    Propagated to nested scopes when Mixin.evaluated creates a Scope.
    """

    def find_mixin(self, target_symbol: "MixinSymbol") -> "Mixin":
        """
        Navigate the mixin tree to find the mixin for target_symbol.

        Uses the classic linked-list LCA (Lowest Common Ancestor) algorithm:
        1. Align self_symbol and target to the same depth
        2. Walk both up in sync until they meet at the common ancestor
        3. Navigate up from self to the LCA mixin
        4. Navigate down from LCA along target's path via evaluated._children

        Instance scope handling:
        When called from inside an instance scope, the mixin outer chain passes
        through instance mixins that share the same symbol as their static
        counterparts. If the LCA lands directly on an instance mixin (no further
        downward navigation needed), we escape upward to the static mixin and
        re-navigate down. If downward navigation is needed, we stay in the
        instance tree since children correctly inherit instance kwargs.
        """
        from overlay.language import MixinSymbol

        self_symbol = self.symbol
        target = target_symbol

        # Collect target keys for downward navigation
        target_keys: list[Hashable] = []

        # Align to same depth
        steps_up = 0
        while self_symbol.depth > target.depth:
            assert isinstance(self_symbol.outer, MixinSymbol)
            self_symbol = self_symbol.outer
            steps_up += 1
        while target.depth > self_symbol.depth:
            target_keys.append(target.key)
            assert isinstance(target.outer, MixinSymbol)
            target = target.outer

        # Walk both up in sync until they meet (LCA)
        while self_symbol is not target:
            assert isinstance(self_symbol.outer, MixinSymbol)
            assert isinstance(target.outer, MixinSymbol)
            self_symbol = self_symbol.outer
            target_keys.append(target.key)
            target = target.outer
            steps_up += 1

        # Navigate up from self to LCA mixin
        current_mixin = self
        for _ in range(steps_up):
            outer_mixin = current_mixin.outer
            assert isinstance(outer_mixin, Mixin)
            current_mixin = outer_mixin

        # Escape instance boundary when the target is the LCA itself
        # (no downward navigation). References cannot point into instances,
        # so we must resolve to the static mixin.
        if not target_keys:
            while not isinstance(current_mixin.kwargs, KwargsSentinel):
                target_keys.append(current_mixin.symbol.key)
                outer_mixin = current_mixin.outer
                assert isinstance(outer_mixin, Mixin)
                current_mixin = outer_mixin

        # Navigate down from LCA along target's path
        for key in reversed(target_keys):
            scope = current_mixin.evaluated
            assert isinstance(scope, Scope)
            child_symbol = current_mixin.symbol[key]
            current_mixin = scope._children[child_symbol]

        return current_mixin

    @cached_property
    def evaluated(self) -> "object | Scope":
        """
        Evaluate this mixin.

        Dynamically decides based on symbol:
        - If symbol is a scope symbol: returns Scope
        - If symbol is a resource symbol: returns evaluated value
        """
        if self.symbol.is_scope:
            # Scope: construct nested Scope
            return self._construct_scope()
        else:
            # Resource: merge patches and return value
            return self._evaluate_resource()

    def _construct_scope(self) -> Scope:
        """
        Construct a Scope from this mixin.

        Dynamically decides between StaticScope and InstanceScope based on kwargs:
        - KwargsSentinel.STATIC: Returns StaticScope
        - Mapping[str, object]: Returns InstanceScope
        """
        symbol = self.symbol

        # Phase 1: Create all Mixin instances
        all_mixins: dict["MixinSymbol", Mixin] = {
            (child_symbol := symbol[key]): Mixin(
                symbol=child_symbol,
                outer=self,
                kwargs=KwargsSentinel.STATIC if child_symbol.is_scope else self.kwargs,
            )
            for key in symbol
        }

        # Phase 2: Wire dependency references as attributes on each Mixin
        for child_symbol, child_mixin in all_mixins.items():
            dependency_symbols = child_symbol.same_scope_dependencies
            for dependency_symbol in dependency_symbols:
                other_mixin = next(
                    other_mixin
                    for other_symbol, other_mixin in all_mixins.items()
                    if other_symbol.attribute_name == dependency_symbol.attribute_name
                )
                setattr(child_mixin, dependency_symbol.attribute_name, other_mixin)

        # Phase 3: Build _children dict and trigger eager evaluation
        children: dict["MixinSymbol", Mixin] = dict(all_mixins)
        for child_symbol, child_mixin in children.items():
            if child_symbol.is_eager:
                _ = child_mixin.evaluated

        # Phase 4: Create appropriate Scope subclass based on kwargs
        if isinstance(self.kwargs, KwargsSentinel):
            return StaticScope(
                symbol=symbol,
                _outer_mixin=self.outer,
                _children=children,
            )
        else:
            return InstanceScope(
                symbol=symbol,
                _children=children,
            )

    def _evaluate_resource(self) -> object:
        """
        Evaluate by resolving dependencies from _sibling_dependencies and outer.

        IMPORTANT: _sibling_dependencies is ONLY valid for direct children
        (whose definition-site outer matches self.outer). Super mixins have a
        different definition-site outer and their de_bruijn_index=0 dependencies
        refer to siblings in the BASE scope, not our scope. They must always
        resolve via navigation.

        This mirrors V1's Resource.evaluated logic exactly.
        """
        from overlay.language import (
            ElectedMerger,
            MergerElectionSentinel,
        )

        def build_evaluators_for_mixin(mixin: "Mixin") -> tuple[Evaluator, ...]:
            """Build evaluators for a given Mixin."""
            return tuple(
                evaluator_symbol.bind(mixin=self)
                for evaluator_symbol in mixin.symbol.evaluator_symbols
            )

        def find_mixin_by_symbol(target_symbol: "MixinSymbol") -> "Mixin":
            """Find the mixin (self or a super union) matching the target symbol."""
            if self.symbol is target_symbol:
                return self
            return self.find_mixin(target_symbol)

        # Get elected merger info
        elected = self.symbol.elected_merger_index

        # Collect patches from all patchers (excluding elected if applicable)
        def generate_patches() -> Iterator[object]:
            match elected:
                case ElectedMerger(
                    symbol=elected_symbol,
                    evaluator_getter_index=elected_getter_index,
                ):
                    # Collect patches from own evaluators
                    own_evaluators = build_evaluators_for_mixin(self)
                    if self.symbol is elected_symbol:
                        # Exclude the elected evaluator from own
                        for evaluator_index, evaluator in enumerate(own_evaluators):
                            if evaluator_index != elected_getter_index and isinstance(
                                evaluator, Patcher
                            ):
                                yield from evaluator
                    else:
                        # Elected is from super, collect all from own
                        for evaluator in own_evaluators:
                            if isinstance(evaluator, Patcher):
                                yield from evaluator

                    # Collect patches from super union mixins
                    for super_union_symbol in self.symbol.qualified_this:
                        if super_union_symbol is self.symbol:
                            continue
                        super_mixin = self.find_mixin(super_union_symbol)
                        super_evaluators = build_evaluators_for_mixin(super_mixin)
                        if super_mixin.symbol is not elected_symbol:
                            for evaluator in super_evaluators:
                                if isinstance(evaluator, Patcher):
                                    yield from evaluator
                        else:
                            # Exclude the elected evaluator's patcher from super
                            for evaluator_index, evaluator in enumerate(
                                super_evaluators
                            ):
                                if (
                                    evaluator_index != elected_getter_index
                                    and isinstance(evaluator, Patcher)
                                ):
                                    yield from evaluator

                case MergerElectionSentinel.PATCHER_ONLY:
                    # Collect all patches from own and super
                    own_evaluators = build_evaluators_for_mixin(self)
                    for evaluator in own_evaluators:
                        if isinstance(evaluator, Patcher):
                            yield from evaluator
                    for super_union_symbol in self.symbol.qualified_this:
                        if super_union_symbol is self.symbol:
                            continue
                        super_mixin = self.find_mixin(super_union_symbol)
                        super_evaluators = build_evaluators_for_mixin(super_mixin)
                        for evaluator in super_evaluators:
                            if isinstance(evaluator, Patcher):
                                yield from evaluator

        # Handle PATCHER_ONLY case (requires instance scope with kwargs)
        if elected is MergerElectionSentinel.PATCHER_ONLY:
            key = self.symbol.key
            # Check if we have kwargs (instance scope)
            if isinstance(self.kwargs, KwargsSentinel):
                raise ValueError(
                    f"Patcher-only resource '{key}' requires instance scope. "
                    f"Call scope(**kwargs) to create an instance scope with the required value."
                )
            # Get base value from kwargs
            if not isinstance(key, str) or key not in self.kwargs:
                raise ValueError(
                    f"Patcher-only resource '{key}' requires kwargs['{key}'] but it was not provided."
                )
            base_value = self.kwargs[key]
            # Collect all patches and apply as endofunctions
            patches = generate_patches()
            return reduce(
                lambda accumulator, endofunction: endofunction(accumulator),  # type: ignore[operator]
                patches,
                base_value,
            )

        # Get Merger evaluator from elected position
        assert isinstance(elected, ElectedMerger)
        elected_mixin = find_mixin_by_symbol(elected.symbol)
        elected_evaluators = build_evaluators_for_mixin(elected_mixin)
        merger_evaluator = elected_evaluators[elected.evaluator_getter_index]
        assert isinstance(merger_evaluator, Merger)

        return merger_evaluator.merge(generate_patches())


@dataclass(kw_only=True, frozen=True, eq=False)
class Scope(ABC):
    """
    Base class for frozen scope containers.

    Scope does NOT inherit from Mixin.

    _children ALWAYS stores Mixin references (never evaluated values).
    This provides consistency: all children are accessed the same way via .evaluated.

    For is_eager=True resources:
    - Mixin is stored in _children (same as lazy)
    - mixin.evaluated is called during construct_scope() to trigger evaluation
    - The @cached_property caches the result, so subsequent access is instant

    Private resources (is_public=False) are NOT stored in _children.
    They exist only in _sibling_dependencies of Mixin instances that depend on them.

    Subclasses:
    - StaticScope: Created by evaluate() and nested scope access. Has __call__.
    - InstanceScope: Created by StaticScope.__call__(**kwargs). Has kwargs field.
    """

    symbol: Final["MixinSymbol"]

    _children: Final[Mapping["MixinSymbol", "Mixin"]]
    """
    Public child Mixin references keyed by MixinSymbol.
    - ALWAYS stores Mixin (never evaluated values)
    - is_eager=True: Mixin.evaluated already called during construction (cached)
    - is_eager=False: Mixin.evaluated called on first access (lazy)
    - is_public=False: NOT stored here (only in _sibling_dependencies of dependents)
    """

    def __getattr__(self, name: str) -> object:
        """Access child by attribute name."""
        # Find symbol by key
        child_symbol = self.symbol.get(name)
        if child_symbol is None:
            raise AttributeError(name)
        # Private resources are blocked from external access
        if not child_symbol.is_public:
            raise AttributeError(name)
        return self._children[child_symbol].evaluated

    def __getitem__(self, key: Hashable) -> object:
        """Access child by key."""
        child_symbol = self.symbol.get(key)
        if child_symbol is None:
            raise KeyError(key)
        # Private resources are blocked from external access
        if not child_symbol.is_public:
            raise KeyError(key)
        return self._children[child_symbol].evaluated

    def __dir__(self) -> list[str]:
        """Return list of accessible attribute names including resource names."""
        base_attrs = set(super(Scope, self).__dir__())
        for child_symbol in self._children:
            if child_symbol.is_public:
                key = child_symbol.key
                if isinstance(key, str):
                    base_attrs.add(key)
        return sorted(base_attrs)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class StaticScope(Scope):
    """
    Static scope created by evaluate() or nested scope access.

    Can be called with kwargs to create an InstanceScope.
    """

    _outer_mixin: Final["Mixin | OuterSentinel"]
    """
    The outer Mixin that this scope was constructed from.
    Needed by __call__ to create instance scopes with the same outer context.
    """

    def __call__(self, **kwargs: object) -> "InstanceScope":
        """Create an instance scope with the given kwargs."""
        instance_mixin = Mixin(
            symbol=self.symbol,
            outer=self._outer_mixin,
            kwargs=kwargs,
        )
        result = instance_mixin.evaluated
        assert isinstance(result, InstanceScope)
        return result


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class InstanceScope(Scope):
    """
    Instance scope created by StaticScope.__call__(**kwargs).

    Identified by type - does not expose kwargs field.
    Cannot be called again (no __call__ method).
    """


# =============================================================================
# Evaluator Hierarchy
# =============================================================================


@dataclass(kw_only=True, frozen=True, eq=False)
class Evaluator(ABC):
    """
    Base class for V2 resource evaluators.

    NOTE: Does NOT inherit from Node/Evaluator - completely separate hierarchy.

    Each evaluator stores the mixin it belongs to. To resolve dependencies,
    use get_symbols + find_mixin to navigate the mixin tree.
    """

    mixin: Mixin
    """
    The Mixin that holds this Evaluator.

    To resolve dependencies, use get_symbols to find the target symbol,
    then self.mixin.find_mixin(target) to navigate to the target Mixin.
    Call .evaluated on the returned Mixin to get the actual value.
    """


@dataclass(kw_only=True, frozen=True, eq=False)
class Merger(Evaluator, Generic[TPatch_contra, TResult_co], ABC):
    """Evaluator that merges patches to produce a result."""

    @abstractmethod
    def merge(self, patches: Iterator[TPatch_contra]) -> TResult_co:
        """Merge patches to produce the final result."""
        ...


@dataclass(kw_only=True, frozen=True, eq=False)
class Patcher(Evaluator, Iterable[TPatch_co], Generic[TPatch_co], ABC):
    """Evaluator that provides patches."""


@dataclass(kw_only=True, frozen=True, eq=False)
class Semigroup(Merger[T, T], Patcher[T], Generic[T], ABC):
    """Both Merger and Patcher."""


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class FunctionalMerger(Merger[TPatch_contra, TResult_co]):
    """V2 Evaluator for FunctionalMergerDefinition."""

    evaluator_getter: "FunctionalMergerSymbol[TPatch_contra, TResult_co]"

    def merge(self, patches: Iterator[TPatch_contra]) -> TResult_co:
        """Merge patches using the aggregation function.

        The function (e.g., @merge def tags() -> type[frozenset]: return frozenset)
        returns an aggregation function. We call that function with the patches.
        """
        # compiled_function returns a function that takes Mixin and returns
        # the aggregation function (e.g., frozenset, list, etc.)
        aggregation_function = self.evaluator_getter.compiled_function(self.mixin)
        # Call it with the patches
        return aggregation_function(patches)  # type: ignore


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class EndofunctionMerger(Merger[Callable[[TResult], TResult], TResult]):
    """V2 Evaluator for EndofunctionMergerDefinition."""

    evaluator_getter: "EndofunctionMergerSymbol[TResult]"

    def merge(self, patches: Iterator[Callable[[TResult], TResult]]) -> TResult:
        """Merge endofunction patches by applying them to base value."""
        # compiled_function returns a function that takes Mixin and returns
        # the base value for endofunction application
        base_value: TResult = self.evaluator_getter.compiled_function(self.mixin)

        return reduce(
            lambda accumulator, endofunction: endofunction(accumulator),
            patches,
            base_value,
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class SinglePatcher(Patcher[TPatch_co]):
    """V2 Evaluator for SinglePatcherDefinition."""

    evaluator_getter: "SinglePatcherSymbol[TPatch_co]"

    def __iter__(self) -> Iterator[TPatch_co]:
        """Yield the single patch value."""
        # compiled_function returns a function that takes Mixin and returns
        # the patch value
        yield self.evaluator_getter.compiled_function(self.mixin)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class MultiplePatcher(Patcher[TPatch_co]):
    """V2 Evaluator for MultiplePatcherDefinition."""

    evaluator_getter: "MultiplePatcherSymbol[TPatch_co]"

    def __iter__(self) -> Iterator[TPatch_co]:
        """Yield multiple patch values."""
        # compiled_function returns a function that takes Mixin and returns
        # an iterable of patch values
        yield from self.evaluator_getter.compiled_function(self.mixin)


def evaluate(
    *namespaces: "ModuleType | ScopeDefinition",
    modules_public: bool = False,
) -> Scope:
    """
    Resolves a Scope from the given namespaces.

    This is the V2 entrypoint that provides:
    - Single lazy evaluation level (at Mixin.evaluated only)
    - Proper is_public semantics (private resources hidden from attributes)
    - Proper is_eager semantics (eager resources evaluated immediately)
    - Circular dependency support via two-phase construction

    When multiple namespaces are provided, they are union-mounted at the root level.
    Resources from all namespaces are merged according to the merger election algorithm.

    :param namespaces: Modules or namespace definitions (decorated with @scope) to resolve.
    :param modules_public: If True, modules are marked as public, making their submodules
        accessible via attribute access. Defaults to False (private by default).
    :return: The root Scope.

    Example::

        root = evaluate(MyNamespace)
        root = evaluate(Base, Override)  # Union mount
        root = evaluate(my_package, modules_public=True)  # Make modules accessible

    """
    from dataclasses import replace
    from types import ModuleType
    from typing import assert_never

    from overlay.language import (
        MixinSymbol,
        OuterSentinel,
        ScopeDefinition,
        _parse_package,
    )

    assert namespaces, "evaluate() requires at least one namespace"

    def to_scope_definition(
        namespace: ModuleType | ScopeDefinition,
    ) -> ScopeDefinition:
        if isinstance(namespace, ScopeDefinition):
            return namespace
        if isinstance(namespace, ModuleType):
            definition = _parse_package(namespace)
            if modules_public:
                return replace(definition, is_public=True)
            return definition
        assert_never(namespace)

    definitions = tuple(to_scope_definition(namespace) for namespace in namespaces)

    root_symbol = MixinSymbol(origin=definitions)

    # Create a synthetic root Mixin to enable lexical scope navigation
    # This is needed so that children of the root scope can navigate up
    # to find parent scope dependencies (via get_mixin)
    root_mixin = Mixin(
        symbol=root_symbol,
        outer=OuterSentinel.ROOT,
        kwargs=KwargsSentinel.STATIC,  # Root is always static
    )

    # Evaluate the root mixin to get the Scope
    result = root_mixin.evaluated
    assert isinstance(result, Scope)
    return result


# Re-export types needed by TYPE_CHECKING imports
if TYPE_CHECKING:
    from types import ModuleType

    from overlay.language import ScopeDefinition

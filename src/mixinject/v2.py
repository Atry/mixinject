"""
MixinV2 and ScopeV2 implementation for proper is_local and is_eager support.

This module provides a cleaner architecture with:
- Single lazy evaluation level (at MixinV2.evaluated only)
- Frozen ScopeV2 containers
- Proper circular dependency support via two-phase construction
- Correct is_local and is_eager semantics

NOTE: This module does NOT include dynamic class generation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property, reduce
from inspect import Parameter
import logging
from typing import (
    TYPE_CHECKING,
    Callable,
    Final,
    Generic,
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    TypeVar,
    final,
)

from mixinject import HasDict

if TYPE_CHECKING:
    from mixinject import (
        EndofunctionMergerSymbol,
        FunctionalMergerSymbol,
        MixinSymbol,
        MultiplePatcherSymbol,
        OuterSentinel,
        ResolvedReference,
        SinglePatcherSymbol,
        SymbolIndexSentinel,
    )

_logger: Final[logging.Logger] = logging.getLogger(__name__)

T = TypeVar("T")
TPatch_co = TypeVar("TPatch_co", covariant=True)
TPatch_contra = TypeVar("TPatch_contra", contravariant=True)
TResult_co = TypeVar("TResult_co", covariant=True)
TResult = TypeVar("TResult")


def get_dependency_symbols(symbol: "MixinSymbol") -> Sequence["MixinSymbol"]:
    """
    Get MixinSymbols that this symbol depends on from the same scope (levels_up=0).

    Mirrors V1's _compile_function_with_mixin logic for same-name skip:
    - Normal params: search from symbol.outer (containing scope)
    - Same-name params (param.name == symbol.key): search from symbol.outer.outer

    Only returns dependencies with effective levels_up=0 (same scope as symbol).

    :param symbol: The MixinSymbol to analyze for dependencies.
    :return: Sequence of MixinSymbols that are dependencies from the same scope.
    """
    from inspect import signature
    from mixinject import (
        EvaluatorDefinition,
        MixinSymbol,
        OuterSentinel,
        RelativeReferenceSentinel,
        _get_param_resolved_reference,
    )

    result: list[MixinSymbol] = []
    outer = symbol.outer

    # Only process if we have a parent scope (MixinSymbol) to look up dependencies
    if not isinstance(outer, MixinSymbol):
        return tuple(result)

    for definition in symbol.definitions:
        if isinstance(definition, EvaluatorDefinition):
            # Get the function from the definition
            if hasattr(definition, "function"):
                function = definition.function
                sig = signature(function)
                for param in sig.parameters.values():
                    # Skip positional-only parameters (used for patches)
                    if param.kind == param.POSITIONAL_ONLY:
                        continue

                    # Same-name skip logic (fixture reference semantics)
                    # Mirrors V1's _compile_function_with_mixin
                    if param.name == symbol.key:
                        # Same-name: search from outer.outer, add 1 to levels_up
                        if isinstance(outer.outer, OuterSentinel):
                            # Same-name at root level - not a sibling dependency
                            continue
                        search_symbol = outer.outer
                        extra_levels = 1
                    else:
                        # Normal: search from outer
                        search_symbol = outer
                        extra_levels = 0

                    resolved_ref = _get_param_resolved_reference(
                        param.name, search_symbol
                    )
                    if resolved_ref is not RelativeReferenceSentinel.NOT_FOUND:
                        # Effective levels_up accounts for same-name skip
                        effective_levels_up = resolved_ref.levels_up + extra_levels
                        # Only include dependencies with levels_up=0 (same scope)
                        if effective_levels_up == 0:
                            result.append(resolved_ref.target_symbol)

    return tuple(result)


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, eq=False)
class MixinV2(HasDict):
    """
    Lazy evaluation wrapper for resources and scopes.

    MixinV2 is mutable (NOT frozen) to support two-phase construction
    for circular dependencies within the same ScopeV2.

    All lazy evaluation happens ONLY at MixinV2.evaluated level.
    Dynamically decides whether to evaluate to a resource value or ScopeV2.

    NOTE: Does NOT inherit from Node/Mixin - completely separate hierarchy.
    Inherits from HasDict to support @cached_property with slots=True.
    """

    symbol: Final["MixinSymbol"]

    outer: Final["MixinV2 | OuterSentinel"]
    """
    The outer MixinV2 (parent scope), or OuterSentinel.ROOT for root.

    To find parent scope dependencies:
    - Evaluate outer.evaluated to get the parent ScopeV2
    - Then access the dependency from that ScopeV2
    """

    lexical_outer_index: Final["SymbolIndexSentinel | int"]
    """Index for lexical scope resolution."""

    # Mutable field for two-phase construction (circular dependency support)
    _sibling_dependencies: "Mapping[str, MixinV2]" = field(init=False)
    """
    References to sibling MixinV2 instances that THIS mixin depends on.
    Keyed by MixinSymbol.attribute_name (str). Only contains dependencies from same scope.
    Set after construction via object.__setattr__.

    Using attribute_name (str) instead of key (Hashable) prepares for future JIT optimization.

    Only valid for direct children (lexical_outer_index == OWN).
    Super mixins (lexical_outer_index != OWN) do NOT use this field.

    TODO: Nephew-uncle dependency support
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Currently _sibling_dependencies only contains sibling-to-sibling dependencies
    within the same scope. Nephew-uncle dependencies (where a nested scope's resource
    depends on its parent's sibling, i.e., an "uncle") are NOT supported.

    This limitation exists because we want lazy compilation for nested scopes (nephews).
    If we were to include nephew-uncle dependencies in _sibling_dependencies, we would
    need to eagerly analyze all nested scopes at construction time, defeating laziness.

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

    Future solution: Add a @friend decorator that marks a scope for Ahead-Of-Time
    analysis. When applied, the scope's nested resources would be analyzed at
    construction time, allowing nephew-uncle dependencies to be wired into
    _sibling_dependencies. This would enable nephews to access uncle's @local resources.
    """

    @cached_property
    def strict_super_mixins(self) -> tuple["MixinV2", ...]:
        """
        Get super MixinV2 instances for multiple inheritance support.

        Similar to V1's Mixin.strict_super_mixins.
        Returns MixinV2 instances corresponding to symbol.strict_super_indices.
        """
        return tuple(self._generate_strict_super_mixins())

    def _generate_strict_super_mixins(self) -> Iterator["MixinV2"]:
        """
        Generate super MixinV2 instances following V1's algorithm.

        For each nested_index in symbol.strict_super_indices:
        - OuterBaseIndex(i): Create child of outer's i-th super with lexical_outer_index=i
        - OwnBaseIndex(i): Resolve own base reference using self.lexical_outer_index
        - OWN: Return self

        NOTE: Super mixins do NOT use _sibling_dependencies because their
        lexical_outer_index != OWN. They always resolve dependencies via navigation.
        This is handled correctly in _evaluate_resource().
        """
        # Import here to avoid circular imports
        from mixinject import OuterBaseIndex, OwnBaseIndex, SymbolIndexSentinel

        for nested_index in self.symbol.strict_super_indices.values():
            match nested_index.primary_index:
                case OuterBaseIndex(index=index):
                    # Get the i-th super mixin from our outer
                    assert isinstance(self.outer, MixinV2)
                    base_mixin = self.outer.get_super(index)
                    # Find our symbol's counterpart in the base mixin's symbol
                    child_symbol = base_mixin.symbol[self.symbol.key]
                    # Create with lexical_outer_index=index (points to base_mixin)
                    # No _sibling_dependencies needed - super mixins resolve via navigation
                    direct_mixin = MixinV2(
                        symbol=child_symbol,
                        outer=self.outer,  # Same outer as us
                        lexical_outer_index=index,  # KEY: Different from OWN!
                    )
                    # Set empty _sibling_dependencies (super mixins don't use it)
                    object.__setattr__(direct_mixin, "_sibling_dependencies", {})

                case OwnBaseIndex(index=index):
                    # Resolve using our own base reference
                    resolved_reference = self.symbol.resolved_bases[index]
                    # Pass OUR lexical_outer_index to the resolution
                    direct_mixin = resolved_reference.get_mixin_v2(
                        outer=self,
                        lexical_outer_index=self.lexical_outer_index,
                    )

                case SymbolIndexSentinel.OWN:
                    direct_mixin = self

            # Navigate to the secondary index within the direct mixin
            yield direct_mixin.get_super(nested_index.secondary_index)

    def get_super(self, super_index: "SymbolIndexSentinel | int") -> "MixinV2":
        """
        Get a super mixin by index.

        :param super_index: OWN returns self, int returns strict_super_mixins[index]
        :return: The super MixinV2.
        """
        from mixinject import SymbolIndexSentinel

        match super_index:
            case SymbolIndexSentinel.OWN:
                return self
            case int() as index:
                return self.strict_super_mixins[index]

    @property
    def lexical_outer(self) -> "MixinV2":
        """
        Get the lexical outer MixinV2 for dependency resolution.

        - If lexical_outer_index is OWN: returns outer (or self for root)
        - If lexical_outer_index is int: returns outer.strict_super_mixins[index]
        """
        from mixinject import SymbolIndexSentinel

        match self.lexical_outer_index:
            case SymbolIndexSentinel.OWN:
                if isinstance(self.outer, MixinV2):
                    return self.outer
                return self  # Root mixin
            case int() as index:
                assert isinstance(self.outer, MixinV2)
                return self.outer.strict_super_mixins[index]

    def resolve_dependency(self, ref: "ResolvedReference") -> "MixinV2":
        """
        Resolve a dependency reference to a MixinV2.

        Returns MixinV2, NOT the evaluated value.
        The caller calls .evaluated when it actually needs the value.
        This preserves laziness - if the caller doesn't use a dependency,
        that dependency is never evaluated.

        :param ref: The resolved reference to resolve.
        :return: The target MixinV2 (call .evaluated for actual value).
        """
        from mixinject import SymbolIndexSentinel

        # Only use _sibling_dependencies when BOTH conditions are met:
        # 1. levels_up == 0 (same scope dependency)
        # 2. lexical_outer_index == OWN (we are a direct child, not a super mixin)
        if ref.levels_up == 0 and self.lexical_outer_index is SymbolIndexSentinel.OWN:
            # Direct child with same-scope dependency: use _sibling_dependencies
            # Keyed by attribute_name (str) for future JIT optimization
            attr_name = ref.target_symbol.attribute_name
            if attr_name in self._sibling_dependencies:
                # Returns MixinV2 directly (caller will call .evaluated when needed)
                return self._sibling_dependencies[attr_name]
            # Fallback to navigation if not in _sibling_dependencies (lazy scopes)

        # Super mixins (lexical_outer_index != OWN) OR parent scope deps:
        # Always resolve via navigation
        # Pass OUR lexical_outer_index to follow the correct inheritance chain
        return ref.get_mixin_v2(
            outer=self,
            lexical_outer_index=self.lexical_outer_index,
        )

    @cached_property
    def evaluated(self) -> "object | ScopeV2":
        """
        Evaluate this mixin.

        Dynamically decides based on symbol:
        - If symbol is a scope symbol: returns ScopeV2
        - If symbol is a resource symbol: returns evaluated value
        """
        if self.symbol.is_scope:
            # Scope: construct nested ScopeV2
            # Pass self as the outer_mixin for children of this scope
            return construct_scope_v2(
                symbol=self.symbol,
                outer_mixin=self,
            )
        else:
            # Resource: merge patches and return value
            return self._evaluate_resource()

    def _evaluate_resource(self) -> object:
        """
        Evaluate by resolving dependencies from _sibling_dependencies and outer.

        IMPORTANT: _sibling_dependencies is ONLY valid for direct children
        (where lexical_outer_index=OWN). Super mixins have lexical_outer_index=int
        and their levels_up=0 dependencies refer to siblings in the BASE scope,
        not our scope. They must always resolve via navigation.

        This mirrors V1's Resource.evaluated logic exactly.
        """
        from mixinject import (
            ElectedMerger,
            MergerElectionSentinel,
            SymbolIndexSentinel,
        )

        def build_evaluators_for_mixin(mixin: "MixinV2") -> list[EvaluatorV2]:
            """Build evaluators for a given MixinV2."""
            result: list[EvaluatorV2] = []
            for evaluator_symbol in mixin.symbol.evaluator_symbols:
                result.append(evaluator_symbol.bind_v2(mixin=mixin))
            return result

        # Get elected merger info
        elected = self.symbol.elected_merger_index

        # Collect patches from all patchers (excluding elected if applicable)
        def generate_patches() -> Iterator[object]:
            match elected:
                case ElectedMerger(
                    symbol_index=elected_symbol_index,
                    evaluator_getter_index=elected_getter_index,
                ):
                    # Collect patches from own evaluators
                    own_evaluators = build_evaluators_for_mixin(self)
                    if elected_symbol_index is SymbolIndexSentinel.OWN:
                        # Exclude the elected evaluator from own
                        for evaluator_index, evaluator in enumerate(own_evaluators):
                            if evaluator_index != elected_getter_index and isinstance(
                                evaluator, PatcherV2
                            ):
                                yield from evaluator
                    else:
                        # Elected is from super, collect all from own
                        for evaluator in own_evaluators:
                            if isinstance(evaluator, PatcherV2):
                                yield from evaluator

                    # Collect patches from super mixins
                    for index, super_mixin in enumerate(self.strict_super_mixins):
                        super_evaluators = build_evaluators_for_mixin(super_mixin)
                        if index != elected_symbol_index:
                            for evaluator in super_evaluators:
                                if isinstance(evaluator, PatcherV2):
                                    yield from evaluator
                        else:
                            # Exclude the elected evaluator's patcher from super
                            for evaluator_index, evaluator in enumerate(
                                super_evaluators
                            ):
                                if evaluator_index != elected_getter_index and isinstance(
                                    evaluator, PatcherV2
                                ):
                                    yield from evaluator

                case MergerElectionSentinel.PATCHER_ONLY:
                    # Collect all patches from own and super
                    own_evaluators = build_evaluators_for_mixin(self)
                    for evaluator in own_evaluators:
                        if isinstance(evaluator, PatcherV2):
                            yield from evaluator
                    for super_mixin in self.strict_super_mixins:
                        super_evaluators = build_evaluators_for_mixin(super_mixin)
                        for evaluator in super_evaluators:
                            if isinstance(evaluator, PatcherV2):
                                yield from evaluator

        # Handle PATCHER_ONLY case (requires instance scope with kwargs)
        if elected is MergerElectionSentinel.PATCHER_ONLY:
            # For V2, we don't support InstanceScope yet
            # This would require outer to be an InstanceScope with kwargs
            raise NotImplementedError(
                f"Patcher-only resource '{self.symbol.key}' requires instance scope, "
                "which is not yet supported in V2"
            )

        # Get Merger evaluator from elected position
        assert isinstance(elected, ElectedMerger)
        elected_mixin = self.get_super(elected.symbol_index)
        elected_evaluators = build_evaluators_for_mixin(elected_mixin)
        merger_evaluator = elected_evaluators[elected.evaluator_getter_index]
        assert isinstance(merger_evaluator, MergerV2)

        return merger_evaluator.merge(generate_patches())


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class ScopeV2:
    """
    Frozen container for MixinV2 references.

    ScopeV2 does NOT inherit from MixinV2.

    _children ALWAYS stores MixinV2 references (never evaluated values).
    This provides consistency: all children are accessed the same way via .evaluated.

    For is_eager=True resources:
    - MixinV2 is stored in _children (same as lazy)
    - mixin.evaluated is called during construct_scope_v2() to trigger evaluation
    - The @cached_property caches the result, so subsequent access is instant

    Local resources (is_local=True) are NOT stored in _children.
    They exist only in _sibling_dependencies of MixinV2 instances that depend on them.
    """

    symbol: Final["MixinSymbol"]

    _children: Final[Mapping["MixinSymbol", "MixinV2"]]
    """
    Public child MixinV2 references keyed by MixinSymbol.
    - ALWAYS stores MixinV2 (never evaluated values)
    - is_eager=True: MixinV2.evaluated already called during construction (cached)
    - is_eager=False: MixinV2.evaluated called on first access (lazy)
    - is_local=True: NOT stored here (only in _sibling_dependencies of dependents)
    """

    def __getattr__(self, name: str) -> object:
        """Access child by attribute name."""
        if name.startswith("_"):
            raise AttributeError(name)
        # Find symbol by key
        child_symbol = self.symbol.get(name)
        if child_symbol is None:
            raise AttributeError(name)
        # Local resources are NOT in _children
        if child_symbol not in self._children:
            raise AttributeError(name)
        return self._children[child_symbol].evaluated

    def __getitem__(self, key: Hashable) -> object:
        """Access child by key."""
        child_symbol = self.symbol.get(key)
        if child_symbol is None:
            raise KeyError(key)
        # Local resources are NOT in _children
        if child_symbol not in self._children:
            raise KeyError(key)
        return self._children[child_symbol].evaluated


def construct_scope_v2(
    symbol: "MixinSymbol",
    outer_mixin: "MixinV2 | OuterSentinel",
) -> ScopeV2:
    """
    Two-phase construction for ScopeV2 with circular dependency support.

    Phase 1: Create all MixinV2 instances (enables circular dependency references)
    Phase 2: Wire _sibling_dependencies for dependency resolution
    Phase 3: Build _children dict (excluding local, eager values stored)

    :param symbol: The MixinSymbol for this scope.
    :param outer_mixin: The parent scope's MixinV2, or OuterSentinel.ROOT for root.
    :return: A ScopeV2 instance.
    """
    from mixinject import SymbolIndexSentinel

    # Phase 1: Create all MixinV2 instances
    # outer_mixin is shared by all children (they're all in the same scope)
    all_mixins: dict["MixinSymbol", MixinV2] = {}
    for key in symbol:
        child_symbol = symbol[key]
        mixin = MixinV2(
            symbol=child_symbol,
            outer=outer_mixin,
            lexical_outer_index=SymbolIndexSentinel.OWN,
        )
        all_mixins[child_symbol] = mixin

    # Phase 2: Wire dependency references (_sibling_dependencies)
    # Each MixinV2 only gets references to its actual dependencies (by attribute_name)
    # Keyed by attribute_name (str) for future JIT optimization
    for child_symbol, mixin in all_mixins.items():
        # Get dependency symbols from the symbol's resolved references
        dependency_symbols = get_dependency_symbols(child_symbol)
        sibling_deps: dict[str, MixinV2] = {}
        for dep_sym in dependency_symbols:
            # Look up by attribute_name in all_mixins since dep_sym might be from
            # a different branch in union mounts
            for other_symbol, other_mixin in all_mixins.items():
                if other_symbol.attribute_name == dep_sym.attribute_name:
                    sibling_deps[dep_sym.attribute_name] = other_mixin
                    break
        object.__setattr__(mixin, "_sibling_dependencies", sibling_deps)

    # Phase 3: Build _children dict (excluding local), trigger eager evaluation
    children: dict["MixinSymbol", MixinV2] = {}

    for child_symbol, mixin in all_mixins.items():
        if child_symbol.is_local:
            # Local resources are NOT added to _children
            # They exist only in _sibling_dependencies of other MixinV2 instances
            continue

        # Always store MixinV2 in _children (consistent access pattern)
        children[child_symbol] = mixin

        if child_symbol.is_eager:
            # Eager: trigger evaluation NOW (result cached by @cached_property)
            _ = mixin.evaluated

    # Phase 4: Create frozen ScopeV2
    return ScopeV2(
        symbol=symbol,
        _children=children,
    )


# =============================================================================
# EvaluatorV2 Hierarchy
# =============================================================================


@dataclass(kw_only=True, frozen=True, eq=False)
class EvaluatorV2(ABC):
    """
    Base class for V2 resource evaluators.

    NOTE: Does NOT inherit from Node/Evaluator - completely separate hierarchy.

    Each evaluator stores the mixin it belongs to. To resolve dependencies,
    call self.mixin.resolve_dependency(ref) which returns MixinV2.
    Then call .evaluated on the returned MixinV2 to get the actual value.
    """

    mixin: MixinV2
    """
    The MixinV2 that holds this EvaluatorV2.

    To resolve dependencies, call self.mixin.resolve_dependency(ref).
    This returns MixinV2, NOT the evaluated value.
    The caller calls .evaluated when it actually needs the dependency value.
    """


@dataclass(kw_only=True, frozen=True, eq=False)
class MergerV2(EvaluatorV2, Generic[TPatch_contra, TResult_co], ABC):
    """EvaluatorV2 that merges patches to produce a result."""

    @abstractmethod
    def merge(self, patches: Iterator[TPatch_contra]) -> TResult_co:
        """Merge patches to produce the final result."""
        ...


@dataclass(kw_only=True, frozen=True, eq=False)
class PatcherV2(EvaluatorV2, Iterable[TPatch_co], Generic[TPatch_co], ABC):
    """EvaluatorV2 that provides patches."""


@dataclass(kw_only=True, frozen=True, eq=False)
class SemigroupV2(MergerV2[T, T], PatcherV2[T], Generic[T], ABC):
    """Both MergerV2 and PatcherV2."""


def _resolve_dependencies_v2(
    function: Callable[..., T],
    mixin: MixinV2,
    current_key: "Hashable | None" = None,
) -> dict[str, object]:
    """
    Resolve function dependencies using the mixin's resolve_dependency method.

    Uses lexical scoping to find dependencies - traverses up the MixinSymbol
    chain to find each parameter, properly tracking levels_up.

    Implements same-name skip logic (fixture reference semantics):
    when current_key is provided and matches a parameter name, the search
    starts from outer_symbol.outer and adds 1 to levels_up.

    :param function: The function whose parameters need dependency resolution.
    :param mixin: The MixinV2 whose resolve_dependency method is used.
    :param current_key: The key of the resource being resolved (for same-name skip).
    :return: Dict mapping parameter names to resolved values.
    """
    from inspect import signature
    from mixinject import (
        MixinSymbol,
        OuterSentinel,
        RelativeReferenceSentinel,
        ResolvedReference,
        _get_param_resolved_reference,
    )

    resolved_kwargs: dict[str, object] = {}
    sig = signature(function)
    outer_symbol = mixin.symbol.outer

    for param in sig.parameters.values():
        # Skip positional-only first parameter (used for patches in mergers)
        if param.kind == param.POSITIONAL_ONLY:
            continue

        # Use lexical scoping to find the dependency (traverses up scope chain)
        if isinstance(outer_symbol, MixinSymbol):
            # Same-name skip logic (fixture reference semantics)
            # Mirrors V1's _compile_function_with_mixin
            if current_key is not None and param.name == current_key:
                # Same-name: search from outer_symbol.outer, add 1 to levels_up
                if isinstance(outer_symbol.outer, OuterSentinel):
                    # Same-name at root level - dependency not found
                    raise LookupError(
                        f"Resource '{current_key}' depends on '{param.name}' "
                        f"which does not exist in scope"
                    )
                search_symbol = outer_symbol.outer
                extra_levels = 1
            else:
                # Normal: search from outer_symbol
                search_symbol = outer_symbol
                extra_levels = 0

            ref = _get_param_resolved_reference(param.name, search_symbol)
            if ref is RelativeReferenceSentinel.NOT_FOUND:
                # Dependency not found - raise error like V1
                raise LookupError(
                    f"Resource '{current_key}' depends on '{param.name}' "
                    f"which does not exist in scope"
                )
            # Adjust levels_up for same-name skip
            if extra_levels > 0:
                ref = ResolvedReference(
                    levels_up=ref.levels_up + extra_levels,
                    path=ref.path,
                    target_symbol=ref.target_symbol,
                )
            # Resolve dependency: get MixinV2, then call .evaluated to get value
            dependency_mixin = mixin.resolve_dependency(ref)
            resolved_kwargs[param.name] = dependency_mixin.evaluated

    return resolved_kwargs


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class FunctionalMergerV2(MergerV2[TPatch_contra, TResult_co]):
    """V2 Evaluator for FunctionalMergerDefinition."""

    evaluator_getter: "FunctionalMergerSymbol[TPatch_contra, TResult_co]"

    def merge(self, patches: Iterator[TPatch_contra]) -> TResult_co:
        """Merge patches using the aggregation function.

        The function (e.g., @merge def tags() -> type[frozenset]: return frozenset)
        returns an aggregation function. We call that function with the patches.
        """
        function = self.evaluator_getter.definition.function
        resolved_kwargs = _resolve_dependencies_v2(
            function,
            self.mixin,
            current_key=self.evaluator_getter.symbol.key,
        )

        # Get the aggregation function (e.g., frozenset, list, etc.)
        aggregation_function = function(**resolved_kwargs)
        # Call it with the patches
        return aggregation_function(patches)  # type: ignore


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class EndofunctionMergerV2(MergerV2[Callable[[TResult], TResult], TResult]):
    """V2 Evaluator for EndofunctionMergerDefinition."""

    evaluator_getter: "EndofunctionMergerSymbol[TResult]"

    def merge(self, patches: Iterator[Callable[[TResult], TResult]]) -> TResult:
        """Merge endofunction patches by applying them to base value."""
        function = self.evaluator_getter.definition.function
        resolved_kwargs = _resolve_dependencies_v2(
            function,
            self.mixin,
            current_key=self.evaluator_getter.symbol.key,
        )
        base_value: TResult = function(**resolved_kwargs)  # type: ignore

        return reduce(
            lambda accumulator, endofunction: endofunction(accumulator),
            patches,
            base_value,
        )


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class SinglePatcherV2(PatcherV2[TPatch_co]):
    """V2 Evaluator for SinglePatcherDefinition."""

    evaluator_getter: "SinglePatcherSymbol[TPatch_co]"

    def __iter__(self) -> Iterator[TPatch_co]:
        """Yield the single patch value."""
        function = self.evaluator_getter.definition.function
        resolved_kwargs = _resolve_dependencies_v2(
            function,
            self.mixin,
            current_key=self.evaluator_getter.symbol.key,
        )
        yield function(**resolved_kwargs)  # type: ignore


@final
@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class MultiplePatcherV2(PatcherV2[TPatch_co]):
    """V2 Evaluator for MultiplePatcherDefinition."""

    evaluator_getter: "MultiplePatcherSymbol[TPatch_co]"

    def __iter__(self) -> Iterator[TPatch_co]:
        """Yield multiple patch values."""
        function = self.evaluator_getter.definition.function
        resolved_kwargs = _resolve_dependencies_v2(
            function,
            self.mixin,
            current_key=self.evaluator_getter.symbol.key,
        )
        yield from function(**resolved_kwargs)  # type: ignore


def evaluate_v2(
    *namespaces: "ModuleType | ScopeDefinition",
) -> ScopeV2:
    """
    Resolves a ScopeV2 from the given namespaces.

    This is the V2 entrypoint that provides:
    - Single lazy evaluation level (at MixinV2.evaluated only)
    - Proper is_local semantics (local resources hidden from attributes)
    - Proper is_eager semantics (eager resources evaluated immediately)
    - Circular dependency support via two-phase construction

    When multiple namespaces are provided, they are union-mounted at the root level.
    Resources from all namespaces are merged according to the merger election algorithm.

    :param namespaces: Modules or namespace definitions (decorated with @scope) to resolve.
    :return: The root ScopeV2.

    Example::

        root = evaluate_v2(MyNamespace)
        root = evaluate_v2(Base, Override)  # Union mount

    """
    from types import ModuleType
    from typing import assert_never

    from mixinject import (
        MixinSymbol,
        OuterSentinel,
        ScopeDefinition,
        SymbolIndexSentinel,
        _parse_package,
    )

    assert namespaces, "evaluate_v2() requires at least one namespace"

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

    # Create a synthetic root MixinV2 to enable lexical scope navigation
    # This is needed so that children of the root scope can navigate up
    # to find parent scope dependencies (via get_mixin_v2)
    root_mixin = MixinV2(
        symbol=root_symbol,
        outer=OuterSentinel.ROOT,
        lexical_outer_index=SymbolIndexSentinel.OWN,
    )
    object.__setattr__(root_mixin, "_sibling_dependencies", {})

    # Evaluate the root mixin to get the ScopeV2
    result = root_mixin.evaluated
    assert isinstance(result, ScopeV2)
    return result


# Re-export types needed by TYPE_CHECKING imports
if TYPE_CHECKING:
    from types import ModuleType

    from mixinject import ScopeDefinition

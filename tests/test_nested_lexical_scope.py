import pytest
from dataclasses import dataclass
from typing import Any, Final, Iterator, override
from typing import Callable
from mixinject import (
    Merger,
    Patcher,
    Scope,
    StaticScope,
    resource,
    extern,
    patch,
    evaluate,
    scope,
    Definition,
    ScopeSymbol,
    NestedSymbol,
    CapturedScopes,
    RelativeReference as R,
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


class Result:
    def __init__(self, value: str):
        self.value = value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Result):
            return self.value == other.value
        return NotImplemented

    def __repr__(self) -> str:
        return f"Result({self.value!r})"


@dataclass(frozen=True)
class Dual(Patcher[Any], Merger[Any, Any]):
    value: Any
    _scope_class: type[Scope] | None = None

    @property
    @override
    def scope_class(self) -> type[Scope] | None:
        return self._scope_class

    @override
    def merge(self, patches: Iterator[Any]) -> Any:
        return Result(
            f"merger-{self.value}-" + "-".join(sorted(str(p) for p in patches))
        )

    @override
    def __iter__(self) -> Iterator[Any]:
        yield f"patch-{self.value}"


@dataclass(frozen=True)
class PureMerger(Merger[Any, Any]):
    value: Any
    _scope_class: type[Scope] | None = None

    @property
    @override
    def scope_class(self) -> type[Scope] | None:
        return self._scope_class

    @override
    def merge(self, patches: Iterator[Any]) -> Any:
        return Result(
            f"pure-{self.value}-" + "-".join(sorted(str(p) for p in patches))
        )


@dataclass(kw_only=True, slots=True, weakref_slot=True, frozen=True, eq=False)
class _DirectNestedSymbol(NestedSymbol):
    """
    NestedSymbol that directly returns an item without any dependency resolution.

    This test helper implements ``bind`` to return a pre-configured
    Mixin (Merger or Patcher) for testing purposes.
    """

    item: Any

    @override
    def bind(
        self, captured_scopes: CapturedScopes, /
    ) -> Merger[Any, Any] | Patcher[Any]:
        return self.item


@dataclass
class DirectDefinition(Definition):
    """
    Definition that directly returns a _DirectNestedSymbol.

    This test helper's ``compile()`` creates a _DirectNestedSymbol instance
    with the pre-configured Mixin.
    """

    item: Any

    @override
    def compile(
        self, outer: ScopeSymbol, key: str, /
    ) -> _DirectNestedSymbol:
        return _DirectNestedSymbol(
            key=key,
            outer=outer,
            item=self.item,
        )


@pytest.mark.parametrize("scope_class", [StaticScope])
class TestNestedCapturedScopes:
    def test_nested_captured_scopes_lookup(self, scope_class: type[Scope]) -> None:
        """
        Non-same-name parameters can be looked up in outer lexical scope.
        """

        @scope()
        class Outer:
            @resource
            def outer_val() -> Result:
                return Result("outer")

            @scope()
            class Inner:
                @resource
                def inner_val(outer_val: Result) -> Result:
                    # This depends on 'outer_val' which is in Outer scope.
                    return Result(f"inner-{outer_val.value}")

        root = evaluate(Outer)
        assert root.Inner.inner_val == Result("inner-outer")

    def test_evaluate_resource_dual_role_single(self, scope_class: type[Scope]) -> None:
        """Test: Single Dual item -> selected as Merger."""

        @scope()
        class Namespace:
            target = DirectDefinition(Dual("A"))

        root = evaluate(Namespace)
        assert root.target == Result("merger-A-")

    def test_evaluate_resource_dual_and_patch(self, scope_class: type[Scope]) -> None:
        """Test: Dual + Dual -> One is Merger, other is Patch."""

        @scope()
        class Root:
            @scope()
            class N1:
                target = DirectDefinition(Dual("A"))

            @scope()
            class N2:
                target = DirectDefinition(Dual("B"))

            @scope(bases=[
                R(levels_up=0, path=("N1",)),
                R(levels_up=0, path=("N2",)),
            ])
            class Combined:
                pass

        root = evaluate(Root)
        value = root.Combined.target
        # Either merger-A-patch-B or merger-B-patch-A
        assert value == Result("merger-A-patch-B") or value == Result("merger-B-patch-A")

    def test_evaluate_resource_pure_merger_and_dual(
        self, scope_class: type[Scope]
    ) -> None:
        """Test: Pure Merger + Dual -> Pure Merger selected, Dual is Patch."""

        @scope()
        class Root:
            @scope()
            class N1:
                target = DirectDefinition(PureMerger("P"))

            @scope()
            class N2:
                target = DirectDefinition(Dual("D"))

            @scope(bases=[
                R(levels_up=0, path=("N1",)),
                R(levels_up=0, path=("N2",)),
            ])
            class Combined:
                pass

        root = evaluate(Root)
        # Pure P is merger. Dual D is patch.
        assert root.Combined.target == Result("pure-P-patch-D")

    def test_evaluate_resource_multiple_pure_mergers_error(
        self, scope_class: type[Scope]
    ) -> None:
        """Test: Multiple pure mergers -> ValueError."""

        @scope()
        class Root:
            @scope()
            class N1:
                target = DirectDefinition(PureMerger("A"))

            @scope()
            class N2:
                target = DirectDefinition(PureMerger("B"))

            @scope(bases=[
                R(levels_up=0, path=("N1",)),
                R(levels_up=0, path=("N2",)),
            ])
            class Combined:
                pass

        root = evaluate(Root)
        with pytest.raises(ValueError, match="Multiple Factory definitions provided"):
            _ = root.Combined.target

    def test_evaluate_resource_no_merger_error(self, scope_class: type[Scope]) -> None:
        """Test: Only patches (no merger) -> NotImplementedError."""

        @dataclass(frozen=True)
        class PurePatch(Patcher[Any]):
            value: Any

            @override
            def __iter__(self) -> Iterator[Any]:
                yield f"patch-{self.value}"

        @scope()
        class N1:
            target = DirectDefinition(PurePatch("A"))

        root = evaluate(N1)
        with pytest.raises(NotImplementedError, match="No Factory definition provided"):
            _ = root.target

    def test_scope_as_patch(self, scope_class: type[Scope]) -> None:
        """Test: @scope used as a patch for another @scope.

        When Extension depends on resources from Base, it must declare
        those dependencies using @extern to make them visible at compile time.
        """

        @scope()
        class Root:
            @scope()
            class Base:
                @resource
                def val() -> Result:
                    return Result("base")

            @scope()
            class Extension:
                @extern
                def val() -> Result:
                    """Declare that val is expected to be provided by Base."""
                    ...

                @resource
                def extended_val(val: Result) -> Result:
                    return Result(f"{val.value}-extended")

                @resource
                def extra() -> Result:
                    return Result("extra")

            @scope(bases=[
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Extension",)),
            ])
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.extended_val == Result("base-extended")
        assert root.Combined.extra == Result("extra")

    def test_scope_scope_class_resolution(self, scope_class: type[Scope]) -> None:
        """Test: Scope class is determined by the scope declaring extend=."""

        class CustomScope(StaticScope):
            pass

        @scope()
        class Root:
            @scope(scope_class=StaticScope)
            class Base:
                @resource
                def val() -> str:
                    return "base"

            @scope(scope_class=StaticScope)
            class Extension:
                @resource
                def extra() -> str:
                    return "extra"

            # Combined explicitly sets scope_class=CustomScope
            @scope(scope_class=CustomScope, bases=[
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Extension",)),
            ])
            class Combined:
                pass

        root = evaluate(Root)
        # Combined's scope_class (CustomScope) is used
        assert isinstance(root.Combined, CustomScope)

    def test_scope_scope_class_uses_declaring_scope(self, scope_class: type[Scope]) -> None:
        """Test: Combined scope uses its own scope_class, not from extended scopes."""

        class CustomScope(StaticScope):
            pass

        @scope()
        class Root:
            @scope(scope_class=CustomScope)
            class Base:
                @resource
                def val() -> str:
                    return "base"

            @scope(scope_class=StaticScope)
            class Extension:
                @resource
                def extra() -> str:
                    return "extra"

            # Combined uses StaticScope regardless of what Base/Extension use
            @scope(scope_class=StaticScope, bases=[
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Extension",)),
            ])
            class Combined:
                pass

        root = evaluate(Root)
        # Combined uses its own scope_class (StaticScope), not Base's CustomScope
        assert isinstance(root.Combined, StaticScope)
        assert not isinstance(root.Combined, CustomScope)
        # Resources from both Base and Extension are accessible
        assert root.Combined.val == "base"
        assert root.Combined.extra == "extra"
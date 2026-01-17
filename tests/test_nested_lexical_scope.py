import pytest
from dataclasses import dataclass
from typing import Any, Iterator, override
from typing import Callable
from mixinject import (
    Merger,
    Patcher,
    Proxy,
    StaticProxy,
    CachedProxy,
    WeakCachedScope,
    resource,
    extern,
    patch,
    mount,
    scope,
    Definition,
    LexicalScope,
    SymbolTable,
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
    _proxy_class: type[Proxy] | None = None

    @property
    @override
    def proxy_class(self) -> type[Proxy] | None:
        return self._proxy_class

    @override
    def create(self, patches: Iterator[Any]) -> Any:
        return Result(
            f"merger-{self.value}-" + "-".join(sorted(str(p) for p in patches))
        )

    @override
    def __iter__(self) -> Iterator[Any]:
        yield f"patch-{self.value}"


@dataclass(frozen=True)
class PureMerger(Merger[Any, Any]):
    value: Any
    _proxy_class: type[Proxy] | None = None

    @property
    @override
    def proxy_class(self) -> type[Proxy] | None:
        return self._proxy_class

    @override
    def create(self, patches: Iterator[Any]) -> Any:
        return Result(
            f"pure-{self.value}-" + "-".join(sorted(str(p) for p in patches))
        )


@dataclass
class DirectDefinition(Definition):
    item: Any

    @override
    def resolve_symbols(
        self, symbol_table: SymbolTable, resource_name: str, /
    ) -> Callable[[LexicalScope], Merger | Patcher]:
        return lambda lexical_scope: self.item


@pytest.mark.parametrize("proxy_class", [CachedProxy, WeakCachedScope])
class TestNestedLexicalScope:
    def test_nested_lexical_scope_lookup(self, proxy_class: type[Proxy]) -> None:
        """
        Non-same-name parameters can be looked up in outer lexical scope.
        """

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

        root = mount(Outer, root_proxy_class=proxy_class)
        assert root.Inner.inner_val == Result("inner-outer")

    def test_evaluate_resource_dual_role_single(self, proxy_class: type[Proxy]) -> None:
        """Test: Single Dual item -> selected as Merger."""

        class Namespace:
            target = DirectDefinition(Dual("A"))

        root = mount(Namespace, root_proxy_class=proxy_class)
        assert root.target == Result("merger-A-")

    def test_evaluate_resource_dual_and_patch(self, proxy_class: type[Proxy]) -> None:
        """Test: Dual + Dual -> One is Merger, other is Patch."""

        class N1:
            target = DirectDefinition(Dual("A"))

        class N2:
            target = DirectDefinition(Dual("B"))

        root = mount(N1, N2, root_proxy_class=proxy_class)
        val = root.target
        # Either merger-A-patch-B or merger-B-patch-A
        assert val == Result("merger-A-patch-B") or val == Result("merger-B-patch-A")

    def test_evaluate_resource_pure_merger_and_dual(
        self, proxy_class: type[Proxy]
    ) -> None:
        """Test: Pure Merger + Dual -> Pure Merger selected, Dual is Patch."""

        class N1:
            target = DirectDefinition(PureMerger("P"))

        class N2:
            target = DirectDefinition(Dual("D"))

        root = mount(N1, N2, root_proxy_class=proxy_class)
        # Pure P is merger. Dual D is patch.
        assert root.target == Result("pure-P-patch-D")

    def test_evaluate_resource_multiple_pure_mergers_error(
        self, proxy_class: type[Proxy]
    ) -> None:
        """Test: Multiple pure mergers -> ValueError."""

        class N1:
            target = DirectDefinition(PureMerger("A"))

        class N2:
            target = DirectDefinition(PureMerger("B"))

        root = mount(N1, N2, root_proxy_class=proxy_class)
        with pytest.raises(ValueError, match="Multiple Factory definitions provided"):
            _ = root.target

    def test_evaluate_resource_no_merger_error(self, proxy_class: type[Proxy]) -> None:
        """Test: Only patches (no merger) -> NotImplementedError."""

        @dataclass(frozen=True)
        class PurePatch(Patcher[Any]):
            value: Any

            @override
            def __iter__(self) -> Iterator[Any]:
                yield f"patch-{self.value}"

        class N1:
            target = DirectDefinition(PurePatch("A"))

        root = mount(N1, root_proxy_class=proxy_class)
        with pytest.raises(NotImplementedError, match="No Factory definition provided"):
            _ = root.target

    def test_scope_as_patch(self, proxy_class: type[Proxy]) -> None:
        """Test: @scope used as a patch for another @scope.

        When Extension depends on resources from Base, it must declare
        those dependencies using @extern to make them visible at compile time.
        """

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

        class N1:
            sub_scope = Base

        class N2:
            # Extension is used as a patch for sub_scope
            sub_scope = Extension

        root = mount(N1, N2, root_proxy_class=proxy_class)
        assert root.sub_scope.extended_val == Result("base-extended")
        assert root.sub_scope.extra == Result("extra")

    def test_scope_proxy_class_resolution(self, proxy_class: type[Proxy]) -> None:
        """Test: Most derived proxy_class is selected."""

        class CustomProxy(CachedProxy):
            pass

        @scope(proxy_class=CachedProxy)
        class Base:
            @resource
            def val() -> str:
                return "base"

        @scope(proxy_class=CustomProxy)
        class Extension:
            @resource
            def extra() -> str:
                return "extra"

        class N1:
            sub_scope = Base

        class N2:
            sub_scope = Extension

        root = mount(N1, N2, root_proxy_class=proxy_class)
        # CustomProxy is a subclass of CachedProxy, so it should be chosen.
        assert isinstance(root.sub_scope, CustomProxy)
        assert not isinstance(root.sub_scope, WeakCachedScope)

    def test_scope_proxy_class_conflict(self, proxy_class: type[Proxy]) -> None:
        """Test: Conflict between unrelated proxy classes raises TypeError."""

        @scope(proxy_class=WeakCachedScope)
        class Base:
            pass

        @dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
        class CustomProxy(StaticProxy):
            pass

        @scope(proxy_class=CustomProxy)
        class Extension:
            pass

        class N1:
            sub_scope = Base

        class N2:
            sub_scope = Extension

        root = mount(N1, N2, root_proxy_class=proxy_class)
        with pytest.raises(TypeError, match="class conflict"):
            _ = root.sub_scope
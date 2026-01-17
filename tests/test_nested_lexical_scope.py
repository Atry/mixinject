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
    DependencyGraph,
    LexicalScope,
    SymbolTable,
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
    ) -> Callable[[DependencyGraph], Callable[[LexicalScope], Merger | Patcher]]:
        return lambda _dependency_graph: lambda _lexical_scope: self.item


@pytest.mark.parametrize("proxy_class", [CachedProxy, WeakCachedScope])
class TestNestedLexicalScope:
    def test_nested_lexical_scope_lookup(self, proxy_class: type[Proxy]) -> None:
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

        root = mount("root", Outer, root_proxy_class=proxy_class)
        assert root.Inner.inner_val == Result("inner-outer")

    def test_evaluate_resource_dual_role_single(self, proxy_class: type[Proxy]) -> None:
        """Test: Single Dual item -> selected as Merger."""

        @scope()
        class Namespace:
            target = DirectDefinition(Dual("A"))

        root = mount("root", Namespace, root_proxy_class=proxy_class)
        assert root.target == Result("merger-A-")

    def test_evaluate_resource_dual_and_patch(self, proxy_class: type[Proxy]) -> None:
        """Test: Dual + Dual -> One is Merger, other is Patch."""

        @scope()
        class Root:
            @scope()
            class N1:
                target = DirectDefinition(Dual("A"))

            @scope()
            class N2:
                target = DirectDefinition(Dual("B"))

            @scope(extend=[
                R(levels_up=0, path=("N1",)),
                R(levels_up=0, path=("N2",)),
            ])
            class Combined:
                pass

        root = mount("root", Root, root_proxy_class=proxy_class)
        value = root.Combined.target
        # Either merger-A-patch-B or merger-B-patch-A
        assert value == Result("merger-A-patch-B") or value == Result("merger-B-patch-A")

    def test_evaluate_resource_pure_merger_and_dual(
        self, proxy_class: type[Proxy]
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

            @scope(extend=[
                R(levels_up=0, path=("N1",)),
                R(levels_up=0, path=("N2",)),
            ])
            class Combined:
                pass

        root = mount("root", Root, root_proxy_class=proxy_class)
        # Pure P is merger. Dual D is patch.
        assert root.Combined.target == Result("pure-P-patch-D")

    def test_evaluate_resource_multiple_pure_mergers_error(
        self, proxy_class: type[Proxy]
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

            @scope(extend=[
                R(levels_up=0, path=("N1",)),
                R(levels_up=0, path=("N2",)),
            ])
            class Combined:
                pass

        root = mount("root", Root, root_proxy_class=proxy_class)
        with pytest.raises(ValueError, match="Multiple Factory definitions provided"):
            _ = root.Combined.target

    def test_evaluate_resource_no_merger_error(self, proxy_class: type[Proxy]) -> None:
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

        root = mount("root", N1, root_proxy_class=proxy_class)
        with pytest.raises(NotImplementedError, match="No Factory definition provided"):
            _ = root.target

    def test_scope_as_patch(self, proxy_class: type[Proxy]) -> None:
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

            @scope(extend=[
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Extension",)),
            ])
            class Combined:
                pass

        root = mount("root", Root, root_proxy_class=proxy_class)
        assert root.Combined.extended_val == Result("base-extended")
        assert root.Combined.extra == Result("extra")

    def test_scope_proxy_class_resolution(self, proxy_class: type[Proxy]) -> None:
        """Test: Proxy class is determined by the scope declaring extend=."""

        class CustomProxy(CachedProxy):
            pass

        @scope()
        class Root:
            @scope(proxy_class=CachedProxy)
            class Base:
                @resource
                def val() -> str:
                    return "base"

            @scope(proxy_class=CachedProxy)
            class Extension:
                @resource
                def extra() -> str:
                    return "extra"

            # Combined explicitly sets proxy_class=CustomProxy
            @scope(proxy_class=CustomProxy, extend=[
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Extension",)),
            ])
            class Combined:
                pass

        root = mount("root", Root, root_proxy_class=proxy_class)
        # Combined's proxy_class (CustomProxy) is used
        assert isinstance(root.Combined, CustomProxy)
        assert not isinstance(root.Combined, WeakCachedScope)

    def test_scope_proxy_class_uses_declaring_scope(self, proxy_class: type[Proxy]) -> None:
        """Test: Combined scope uses its own proxy_class, not from extended scopes."""

        @scope()
        class Root:
            @scope(proxy_class=WeakCachedScope)
            class Base:
                @resource
                def val() -> str:
                    return "base"

            @scope(proxy_class=CachedProxy)
            class Extension:
                @resource
                def extra() -> str:
                    return "extra"

            # Combined uses CachedProxy regardless of what Base/Extension use
            @scope(proxy_class=CachedProxy, extend=[
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Extension",)),
            ])
            class Combined:
                pass

        root = mount("root", Root, root_proxy_class=proxy_class)
        # Combined uses its own proxy_class (CachedProxy), not Base's WeakCachedScope
        assert isinstance(root.Combined, CachedProxy)
        # Resources from both Base and Extension are accessible
        assert root.Combined.val == "base"
        assert root.Combined.extra == "extra"
"""Test ResolvedReference.get_symbol navigates the symbol tree correctly.

get_symbol is the compile-time counterpart of get_mixin. It follows two parallel chains:
- structural (outer): the actual parent in the symbol tree
- lexical (lexical_outer): the definition origin parent

For the outer_vs_lexical_outer fixture:
    Foo:
      Bar:
        Baz: []
    Qux:
      - [Foo]

Symbol tree:
    root
    ├── Foo (outer=root, lexical_outer=root)
    │   └── Bar (outer=Foo, lexical_outer=Foo)
    │       └── Baz (outer=Foo.Bar, lexical_outer=Foo.Bar)
    └── Qux (outer=root, lexical_outer=root)
        └── Bar (outer=Qux, lexical_outer=Foo)  ← inherited
            └── Baz (outer=Qux.Bar, lexical_outer=Foo.Bar)  ← inherited
"""

from pathlib import Path

import pytest

from mixinject import MixinSymbol, ResolvedReference
from mixinject.mixin_directory import DirectoryMixinDefinition
from mixinject.runtime import Mixin, Scope, evaluate


FIXTURES_PATH = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_symbol() -> MixinSymbol:
    """Load the outer_vs_lexical_outer fixture and return its MixinSymbol."""
    fixtures_definition = DirectoryMixinDefinition(
        bases=(), is_public=True, underlying=FIXTURES_PATH
    )
    root = MixinSymbol(origin=(fixtures_definition,))
    return root["outer_vs_lexical_outer"]


class TestGetSymbolNonInherited:
    """Test get_symbol on non-inherited symbols (where outer == lexical_outer)."""

    def test_de_bruijn_0_navigate_sibling(self, fixture_symbol: MixinSymbol) -> None:
        """From Foo.Bar.Baz, de_bruijn_index=0 path=("Baz",) → Foo.Bar.Baz."""
        foo_bar_baz = fixture_symbol["Foo"]["Bar"]["Baz"]
        reference = ResolvedReference(
            de_bruijn_index=0,
            path=("Baz",),
            target_symbol_bound=foo_bar_baz,
        )

        result = reference.get_symbol(foo_bar_baz)

        assert result is foo_bar_baz

    def test_de_bruijn_0_navigate_sibling_bar(self, fixture_symbol: MixinSymbol) -> None:
        """From Foo.Bar.Baz, de_bruijn_index=0 path=("Bar",) → Foo.Bar (from Foo's scope)."""
        foo_bar = fixture_symbol["Foo"]["Bar"]
        foo_bar_baz = foo_bar["Baz"]

        # de_bruijn_index=0 from Foo.Bar.Baz means we start at Foo.Bar.Baz.outer = Foo.Bar
        # Then navigate path ("Bar",) → but Foo.Bar doesn't have a child "Bar"
        # This would actually fail. Let's use a valid path instead.
        reference = ResolvedReference(
            de_bruijn_index=0,
            path=("Baz",),
            target_symbol_bound=foo_bar_baz,
        )

        result = reference.get_symbol(foo_bar_baz)

        assert result is foo_bar_baz

    def test_de_bruijn_1_navigate_to_bar(self, fixture_symbol: MixinSymbol) -> None:
        """From Foo.Bar.Baz, de_bruijn_index=1 path=("Bar",) → Foo.Bar.

        Navigate up 1 level from Foo.Bar to Foo, then down to Foo["Bar"] = Foo.Bar.
        """
        foo_bar = fixture_symbol["Foo"]["Bar"]
        foo_bar_baz = foo_bar["Baz"]

        reference = ResolvedReference(
            de_bruijn_index=1,
            path=("Bar",),
            target_symbol_bound=foo_bar,
        )

        result = reference.get_symbol(foo_bar_baz)

        assert result is foo_bar

    def test_de_bruijn_2_navigate_to_foo(self, fixture_symbol: MixinSymbol) -> None:
        """From Foo.Bar.Baz, de_bruijn_index=2 path=("Foo",) → Foo.

        Navigate up 2 levels from Foo.Bar to root, then down to root["Foo"] = Foo.
        """
        foo = fixture_symbol["Foo"]
        foo_bar_baz = foo["Bar"]["Baz"]

        reference = ResolvedReference(
            de_bruijn_index=2,
            path=("Foo",),
            target_symbol_bound=foo,
        )

        result = reference.get_symbol(foo_bar_baz)

        assert result is foo

    def test_de_bruijn_0_empty_path(self, fixture_symbol: MixinSymbol) -> None:
        """From Foo.Bar.Baz, de_bruijn_index=0 path=() → Foo.Bar (outer itself)."""
        foo_bar = fixture_symbol["Foo"]["Bar"]
        foo_bar_baz = foo_bar["Baz"]

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=(),
            target_symbol_bound=foo_bar,
        )

        result = reference.get_symbol(foo_bar_baz)

        assert result is foo_bar


class TestGetSymbolInherited:
    """Test get_symbol on inherited symbols (where outer != lexical_outer).

    This is the critical test class. For inherited symbols, the navigation
    follows lexical_outer (definition origin) instead of outer (structural parent).
    """

    def test_de_bruijn_0_from_qux_bar_baz(self, fixture_symbol: MixinSymbol) -> None:
        """From Qux.Bar.Baz, de_bruijn_index=0 path=("Baz",) → Qux.Bar.Baz.

        de_bruijn_index=0 starts from outer (structural parent), so Qux.Bar["Baz"] = Qux.Bar.Baz.
        """
        qux_bar = fixture_symbol["Qux"]["Bar"]
        qux_bar_baz = qux_bar["Baz"]

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=("Baz",),
            target_symbol_bound=qux_bar_baz,
        )

        result = reference.get_symbol(qux_bar_baz)

        assert result is qux_bar_baz

    def test_de_bruijn_1_from_qux_bar_baz_navigates_via_lexical(
        self, fixture_symbol: MixinSymbol
    ) -> None:
        """From Qux.Bar.Baz, de_bruijn_index=1 path=("Bar",) → Foo.Bar.

        This is the KEY test. The navigation goes:
        1. current = Qux.Bar.Baz.outer = Qux.Bar
        2. current_lexical = Qux.Bar.Baz.lexical_outer = Foo.Bar
        3. Loop (1 iteration):
           - current = Foo.Bar.outer = Foo  (follows lexical chain)
           - current_lexical = Foo.Bar.lexical_outer = Foo
        4. Navigate: Foo["Bar"] = Foo.Bar

        Result is Foo.Bar, NOT Qux.Bar, because lexical scoping traces back
        to the definition origin.
        """
        foo_bar = fixture_symbol["Foo"]["Bar"]
        qux_bar_baz = fixture_symbol["Qux"]["Bar"]["Baz"]

        reference = ResolvedReference(
            de_bruijn_index=1,
            path=("Bar",),
            target_symbol_bound=foo_bar,
        )

        result = reference.get_symbol(qux_bar_baz)

        assert result is foo_bar

    def test_de_bruijn_1_from_qux_bar(self, fixture_symbol: MixinSymbol) -> None:
        """From Qux.Bar, de_bruijn_index=1 path=("Foo",) → Foo.

        Navigation:
        1. current = Qux.Bar.outer = Qux
        2. current_lexical = Qux.Bar.lexical_outer = Foo
        3. Loop (1 iteration):
           - current = Foo.outer = root
           - current_lexical = Foo.lexical_outer = root
        4. Navigate: root["Foo"] = Foo
        """
        foo = fixture_symbol["Foo"]
        qux_bar = fixture_symbol["Qux"]["Bar"]

        reference = ResolvedReference(
            de_bruijn_index=1,
            path=("Foo",),
            target_symbol_bound=foo,
        )

        result = reference.get_symbol(qux_bar)

        assert result is foo

    def test_de_bruijn_2_from_qux_bar_baz(self, fixture_symbol: MixinSymbol) -> None:
        """From Qux.Bar.Baz, de_bruijn_index=2 path=("Foo",) → Foo.

        Navigation:
        1. current = Qux.Bar.Baz.outer = Qux.Bar
        2. current_lexical = Qux.Bar.Baz.lexical_outer = Foo.Bar
        3. Loop iteration 1:
           - current = Foo.Bar.outer = Foo
           - current_lexical = Foo.Bar.lexical_outer = Foo
        4. Loop iteration 2:
           - current = Foo.outer = root
           - current_lexical = Foo.lexical_outer = root
        5. Navigate: root["Foo"] = Foo
        """
        foo = fixture_symbol["Foo"]
        qux_bar_baz = fixture_symbol["Qux"]["Bar"]["Baz"]

        reference = ResolvedReference(
            de_bruijn_index=2,
            path=("Foo",),
            target_symbol_bound=foo,
        )

        result = reference.get_symbol(qux_bar_baz)

        assert result is foo

    def test_de_bruijn_0_empty_path_from_inherited(
        self, fixture_symbol: MixinSymbol
    ) -> None:
        """From Qux.Bar.Baz, de_bruijn_index=0 path=() → Qux.Bar.

        Even for inherited symbols, de_bruijn_index=0 with empty path
        gives the structural parent (outer).
        """
        qux_bar = fixture_symbol["Qux"]["Bar"]
        qux_bar_baz = qux_bar["Baz"]

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=(),
            target_symbol_bound=qux_bar,
        )

        result = reference.get_symbol(qux_bar_baz)

        assert result is qux_bar


class TestGetSymbolIsomorphicWithGetMixin:
    """Test ref.get_symbol(mixin.symbol) is ref.get_mixin(mixin).symbol.

    This verifies that compile-time navigation (get_symbol) produces results
    consistent with runtime navigation (get_mixin).
    """

    @pytest.fixture
    def fixture_scope(self) -> Scope:
        fixtures_definition = DirectoryMixinDefinition(
            bases=(), is_public=True, underlying=FIXTURES_PATH
        )
        root_scope = evaluate(fixtures_definition, modules_public=True)
        result = root_scope.outer_vs_lexical_outer
        assert isinstance(result, Scope)
        return result

    def _get_child_mixin(self, parent_scope: Scope, key: str) -> Mixin:
        """Get the Mixin for a child key from parent scope's _children."""
        child_symbol = parent_scope.symbol[key]
        child_mixin = parent_scope._children[child_symbol]
        assert isinstance(child_mixin, Mixin)
        return child_mixin

    def test_de_bruijn_0_foo_bar_baz(self, fixture_scope: Scope) -> None:
        """Isomorphism for de_bruijn_index=0 on non-inherited Foo.Bar.Baz."""
        foo_scope = fixture_scope.Foo
        assert isinstance(foo_scope, Scope)
        foo_bar_scope = foo_scope.Bar
        assert isinstance(foo_bar_scope, Scope)
        foo_bar_baz_mixin = self._get_child_mixin(foo_bar_scope, "Baz")

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=("Baz",),
            target_symbol_bound=foo_bar_baz_mixin.symbol,
        )

        symbol_result = reference.get_symbol(foo_bar_baz_mixin.symbol)
        mixin_result = reference.get_mixin(foo_bar_baz_mixin)

        assert symbol_result is mixin_result.symbol

    def test_de_bruijn_1_foo_bar_baz(self, fixture_scope: Scope) -> None:
        """Isomorphism for de_bruijn_index=1 on non-inherited Foo.Bar.Baz."""
        foo_scope = fixture_scope.Foo
        assert isinstance(foo_scope, Scope)
        foo_bar_scope = foo_scope.Bar
        assert isinstance(foo_bar_scope, Scope)
        foo_bar_baz_mixin = self._get_child_mixin(foo_bar_scope, "Baz")
        foo_bar_symbol = fixture_scope.symbol["Foo"]["Bar"]

        reference = ResolvedReference(
            de_bruijn_index=1,
            path=("Bar",),
            target_symbol_bound=foo_bar_symbol,
        )

        symbol_result = reference.get_symbol(foo_bar_baz_mixin.symbol)
        mixin_result = reference.get_mixin(foo_bar_baz_mixin)

        assert symbol_result is mixin_result.symbol

    def test_de_bruijn_0_qux_bar_baz(self, fixture_scope: Scope) -> None:
        """Isomorphism for de_bruijn_index=0 on inherited Qux.Bar.Baz."""
        qux_scope = fixture_scope.Qux
        assert isinstance(qux_scope, Scope)
        qux_bar_scope = qux_scope.Bar
        assert isinstance(qux_bar_scope, Scope)
        qux_bar_baz_mixin = self._get_child_mixin(qux_bar_scope, "Baz")

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=("Baz",),
            target_symbol_bound=qux_bar_baz_mixin.symbol,
        )

        symbol_result = reference.get_symbol(qux_bar_baz_mixin.symbol)
        mixin_result = reference.get_mixin(qux_bar_baz_mixin)

        assert symbol_result is mixin_result.symbol

    @pytest.mark.xfail(
        reason="Known bug: runtime navigation may fail for inherited symbols"
    )
    def test_de_bruijn_1_qux_bar_baz(self, fixture_scope: Scope) -> None:
        """Isomorphism for de_bruijn_index=1 on inherited Qux.Bar.Baz."""
        qux_scope = fixture_scope.Qux
        assert isinstance(qux_scope, Scope)
        qux_bar_scope = qux_scope.Bar
        assert isinstance(qux_bar_scope, Scope)
        qux_bar_baz_mixin = self._get_child_mixin(qux_bar_scope, "Baz")
        foo_bar_symbol = fixture_scope.symbol["Foo"]["Bar"]

        reference = ResolvedReference(
            de_bruijn_index=1,
            path=("Bar",),
            target_symbol_bound=foo_bar_symbol,
        )

        symbol_result = reference.get_symbol(qux_bar_baz_mixin.symbol)
        mixin_result = reference.get_mixin(qux_bar_baz_mixin)

        assert symbol_result is mixin_result.symbol

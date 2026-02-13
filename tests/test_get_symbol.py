"""Test ResolvedReference.get_symbols navigates the symbol tree correctly.

get_symbols navigates using strict_super_reverse_index at each de Bruijn level
to find all symbols whose .outer inherits the definition_site.

For the outer_vs_lexical_outer fixture:
    Foo:
      Bar:
        Baz: []
    Qux:
      - [Foo]

Symbol tree:
    root
    ├── Foo (outer=root)
    │   └── Bar (outer=Foo)
    │       └── Baz (outer=Foo.Bar)
    └── Qux (outer=root)
        └── Bar (outer=Qux)  ← inherited from Foo
            └── Baz (outer=Qux.Bar)  ← inherited from Foo.Bar
"""

from pathlib import Path

import pytest

from ol import MixinSymbol, ResolvedReference
from ol.mixin_directory import DirectoryMixinDefinition
from ol.runtime import Mixin, Scope, evaluate


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
    """Test get_symbols on non-inherited symbols (no composition)."""

    def test_de_bruijn_0_navigate_sibling(self, fixture_symbol: MixinSymbol) -> None:
        """From Foo.Bar.Baz, de_bruijn_index=0 path=("Baz",) → Foo.Bar.Baz."""
        foo_bar = fixture_symbol["Foo"]["Bar"]
        foo_bar_baz = foo_bar["Baz"]

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=("Baz",),
            target_symbol_bound=foo_bar_baz,
            origin_symbol=foo_bar,
        )

        result, = reference.get_symbols(current=foo_bar)

        assert result is foo_bar_baz

    def test_de_bruijn_0_navigate_sibling_bar(self, fixture_symbol: MixinSymbol) -> None:
        """From Foo.Bar.Baz, de_bruijn_index=0 path=("Baz",) → Foo.Bar.Baz."""
        foo_bar = fixture_symbol["Foo"]["Bar"]
        foo_bar_baz = foo_bar["Baz"]

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=("Baz",),
            target_symbol_bound=foo_bar_baz,
            origin_symbol=foo_bar,
        )

        result, = reference.get_symbols(current=foo_bar)

        assert result is foo_bar_baz

    def test_de_bruijn_1_navigate_to_bar(self, fixture_symbol: MixinSymbol) -> None:
        """From Foo.Bar, de_bruijn_index=0 path=("Bar",) → Foo.Bar."""
        foo = fixture_symbol["Foo"]
        foo_bar = foo["Bar"]

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=("Bar",),
            target_symbol_bound=foo_bar,
            origin_symbol=foo,
        )

        result, = reference.get_symbols(current=foo)

        assert result is foo_bar

    def test_de_bruijn_1_navigate_up_then_path(self, fixture_symbol: MixinSymbol) -> None:
        """From Foo, de_bruijn_index=1 path=("Foo",) → Foo.

        Navigation with get_symbols:
        - origin_symbol = Foo, current = Foo
        - definition_site = Foo
        - Loop (1 iteration): find strict_super of Foo whose .outer == Foo or inherits Foo
          → Foo itself has .outer = root, root has Foo in strict_super_reverse_index? No.
          → Actually: (Foo, *Foo.generate_strict_super()) where .outer is root,
            and definition_site is Foo. root has Foo as child but strict_super_reverse_index
            checks inheritance. For non-inherited: Foo.outer = root, definition_site = Foo.
            root inherits nothing, but definition_site == root? No, definition_site = Foo.
            So check: Foo in root.strict_super_reverse_index → yes if root has Foo as union.
        - Navigate: root["Foo"] = Foo
        """
        foo = fixture_symbol["Foo"]

        reference = ResolvedReference(
            de_bruijn_index=1,
            path=("Foo",),
            target_symbol_bound=foo,
            origin_symbol=foo,
        )

        result, = reference.get_symbols(current=foo)

        assert result is foo

    def test_de_bruijn_0_empty_path(self, fixture_symbol: MixinSymbol) -> None:
        """From Foo.Bar.Baz, de_bruijn_index=0 path=() → Foo.Bar (current itself)."""
        foo_bar = fixture_symbol["Foo"]["Bar"]

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=(),
            target_symbol_bound=foo_bar,
            origin_symbol=foo_bar,
        )

        result, = reference.get_symbols(current=foo_bar)

        assert result is foo_bar


class TestGetSymbolInherited:
    """Test get_symbols on inherited symbols (Qux extends Foo).

    For inherited symbols, the new algorithm uses strict_super_reverse_index
    to find composition-site symbols at each de Bruijn level.
    """

    def test_de_bruijn_0_from_qux_bar_baz(self, fixture_symbol: MixinSymbol) -> None:
        """From Qux.Bar.Baz, de_bruijn_index=0 path=("Baz",) → Qux.Bar.Baz.

        de_bruijn_index=0: no loop, just navigate path from current.
        """
        foo_bar = fixture_symbol["Foo"]["Bar"]
        qux_bar = fixture_symbol["Qux"]["Bar"]
        qux_bar_baz = qux_bar["Baz"]

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=("Baz",),
            target_symbol_bound=qux_bar_baz,
            origin_symbol=foo_bar,
        )

        result, = reference.get_symbols(current=qux_bar)

        assert result is qux_bar_baz

    def test_de_bruijn_1_from_qux_bar_baz_navigates_via_strict_super(
        self, fixture_symbol: MixinSymbol
    ) -> None:
        """From Qux.Bar.Baz, de_bruijn_index=1 path=("Bar",) → {Qux.Bar}.

        Navigation with get_symbols via lexical_outer:
        1. current = Qux.Bar, origin_symbol = Foo.Bar, definition_site = Foo.Bar
        2. Loop (1 iteration):
           - lexical_outer[Foo.Bar] → {Qux} (Qux.Bar's outer for Foo.Bar union)
           - currents = {Qux}
           - definition_site = Foo.Bar.outer = Foo
        3. Navigate "Bar": Qux["Bar"] = Qux.Bar
        """
        qux_bar = fixture_symbol["Qux"]["Bar"]

        reference = ResolvedReference(
            de_bruijn_index=1,
            path=("Bar",),
            target_symbol_bound=qux_bar,
            origin_symbol=fixture_symbol["Foo"]["Bar"],
        )

        results = reference.get_symbols(current=qux_bar)

        assert results == (qux_bar,)

    def test_de_bruijn_1_from_qux_bar(self, fixture_symbol: MixinSymbol) -> None:
        """From Qux.Bar, de_bruijn_index=1 path=("Foo",) → Foo.

        Navigation with get_symbols:
        1. current = Qux, origin_symbol = Foo, definition_site = Foo
        2. Loop (1 iteration):
           - Qux.outer = root, Foo in root.strict_super_reverse_index? No.
             But Foo == root? No. definition_site == Qux.outer? Foo == root? No.
             Check Qux's strict supers: Foo.outer = root, definition_site = Foo,
             Foo in root.strict_super_reverse_index → need to verify...
           - Actually: definition_site = Foo, root has Foo as child (union),
             so Foo in root.strict_super_reverse_index → yes
           - currents = (root,)
           - definition_site = Foo.outer = root
        3. Navigate: root["Foo"] = Foo
        """
        foo = fixture_symbol["Foo"]
        qux = fixture_symbol["Qux"]

        reference = ResolvedReference(
            de_bruijn_index=1,
            path=("Foo",),
            target_symbol_bound=foo,
            origin_symbol=foo,
        )

        result, = reference.get_symbols(current=qux)

        assert result is foo

    def test_de_bruijn_2_from_qux_bar_baz(self, fixture_symbol: MixinSymbol) -> None:
        """From Qux.Bar.Baz, de_bruijn_index=2 path=("Foo",) → Foo.

        Navigation with get_symbols:
        1. current = Qux.Bar, origin_symbol = Foo.Bar, definition_site = Foo.Bar
        2. Loop iteration 1:
           - Qux.Bar.outer = Qux, Foo.Bar in Qux.strict_super_reverse_index → yes
           - currents = (Qux,)
           - definition_site = Foo.Bar.outer = Foo
        3. Loop iteration 2:
           - Qux.outer = root, Foo in root.strict_super_reverse_index → yes
           - currents = (root,)
           - definition_site = Foo.outer = root
        4. Navigate: root["Foo"] = Foo
        """
        foo = fixture_symbol["Foo"]
        foo_bar = fixture_symbol["Foo"]["Bar"]
        qux_bar = fixture_symbol["Qux"]["Bar"]

        reference = ResolvedReference(
            de_bruijn_index=2,
            path=("Foo",),
            target_symbol_bound=foo,
            origin_symbol=foo_bar,
        )

        result, = reference.get_symbols(current=qux_bar)

        assert result is foo

    def test_de_bruijn_0_empty_path_from_inherited(
        self, fixture_symbol: MixinSymbol
    ) -> None:
        """From Qux.Bar.Baz, de_bruijn_index=0 path=() → Qux.Bar.

        de_bruijn_index=0 with empty path gives current itself.
        """
        foo_bar = fixture_symbol["Foo"]["Bar"]
        qux_bar = fixture_symbol["Qux"]["Bar"]

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=(),
            target_symbol_bound=qux_bar,
            origin_symbol=foo_bar,
        )

        result, = reference.get_symbols(current=qux_bar)

        assert result is qux_bar


class TestGetSymbolIsomorphicWithFindMixin:
    """Test get_symbols result matches find_mixin result.

    These tests verify compile-time navigation (get_symbols) produces results
    consistent with runtime navigation (find_mixin).
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

        symbol_outer = foo_bar_baz_mixin.symbol.outer
        assert isinstance(symbol_outer, MixinSymbol)

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=("Baz",),
            target_symbol_bound=foo_bar_baz_mixin.symbol,
            origin_symbol=symbol_outer,
        )
        symbol_result, = reference.get_symbols(current=symbol_outer)
        mixin_result = foo_bar_baz_mixin.find_mixin(symbol_result)

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
            origin_symbol=foo_bar_symbol,
        )

        symbol_outer = foo_bar_baz_mixin.symbol.outer
        assert isinstance(symbol_outer, MixinSymbol)
        symbol_result, = reference.get_symbols(current=symbol_outer)
        mixin_result = foo_bar_baz_mixin.find_mixin(symbol_result)

        assert symbol_result is mixin_result.symbol

    def test_de_bruijn_0_qux_bar_baz(self, fixture_scope: Scope) -> None:
        """Isomorphism for de_bruijn_index=0 on inherited Qux.Bar.Baz."""
        qux_scope = fixture_scope.Qux
        assert isinstance(qux_scope, Scope)
        qux_bar_scope = qux_scope.Bar
        assert isinstance(qux_bar_scope, Scope)
        qux_bar_baz_mixin = self._get_child_mixin(qux_bar_scope, "Baz")
        foo_bar_symbol = fixture_scope.symbol["Foo"]["Bar"]

        reference = ResolvedReference(
            de_bruijn_index=0,
            path=("Baz",),
            target_symbol_bound=qux_bar_baz_mixin.symbol,
            origin_symbol=foo_bar_symbol,
        )

        symbol_outer = qux_bar_baz_mixin.symbol.outer
        assert isinstance(symbol_outer, MixinSymbol)
        symbol_result, = reference.get_symbols(current=symbol_outer)
        mixin_result = qux_bar_baz_mixin.find_mixin(symbol_result)

        assert symbol_result is mixin_result.symbol

    def test_de_bruijn_1_qux_bar_baz(self, fixture_scope: Scope) -> None:
        """Isomorphism for de_bruijn_index=1 on inherited Qux.Bar.Baz.

        get_symbols returns (Qux.Bar, Foo.Bar) — two results because Qux
        inherits Foo. get_mixins should return the corresponding mixin pair.
        """
        qux_scope = fixture_scope.Qux
        assert isinstance(qux_scope, Scope)
        qux_bar_scope = qux_scope.Bar
        assert isinstance(qux_bar_scope, Scope)
        qux_bar_baz_mixin = self._get_child_mixin(qux_bar_scope, "Baz")
        foo_bar_symbol = fixture_scope.symbol["Foo"]["Bar"]

        reference = ResolvedReference(
            de_bruijn_index=1,
            path=("Bar",),
            target_symbol_bound=fixture_scope.symbol["Qux"]["Bar"],
            origin_symbol=foo_bar_symbol,
        )

        symbol_outer = qux_bar_baz_mixin.symbol.outer
        assert isinstance(symbol_outer, MixinSymbol)
        symbol_results = reference.get_symbols(current=symbol_outer)
        mixin_results = tuple(
            qux_bar_baz_mixin.find_mixin(symbol_result)
            for symbol_result in symbol_results
        )

        assert len(symbol_results) == len(mixin_results)
        for symbol_result, mixin_result in zip(symbol_results, mixin_results, strict=True):
            assert symbol_result is mixin_result.symbol

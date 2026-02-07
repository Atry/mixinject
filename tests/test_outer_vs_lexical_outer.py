"""Test that MixinSymbol has distinct outer and lexical_outer properties.

For a MIXIN structure like:
    Foo:
      Bar:
        Baz: []
    Qux:
      - [Foo]

[Qux, Bar, Baz].outer should be [Qux, Bar]  (structural parent in the symbol tree)
[Qux, Bar, Baz].lexical_outer should be [Foo, Bar]  (where definitions originate)

This mirrors the distinction that already exists on Mixin (runtime layer):
- Mixin.outer: runtime parent scope instance
- Mixin.lexical_outer: static prototype context for late-binding
"""

from pathlib import Path

import pytest

from mixinject import MixinSymbol, OuterSentinel
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


class TestMixinSymbolOuterVsLexicalOuter:
    """Test that MixinSymbol distinguishes outer (structural parent) from lexical_outer (definition origin)."""

    def test_foo_bar_baz_outer_is_foo_bar(self, fixture_symbol: MixinSymbol) -> None:
        """[Foo, Bar, Baz].outer should be [Foo, Bar]."""
        foo_bar = fixture_symbol["Foo"]["Bar"]
        foo_bar_baz = foo_bar["Baz"]

        assert isinstance(foo_bar_baz.outer, MixinSymbol)
        assert foo_bar_baz.outer is foo_bar

    def test_foo_bar_baz_lexical_outer_is_foo_bar(self, fixture_symbol: MixinSymbol) -> None:
        """[Foo, Bar, Baz].lexical_outer should be [Foo, Bar] (same as outer for non-inherited)."""
        foo_bar = fixture_symbol["Foo"]["Bar"]
        foo_bar_baz = foo_bar["Baz"]

        assert isinstance(foo_bar_baz.lexical_outer, MixinSymbol)
        assert foo_bar_baz.lexical_outer is foo_bar

    def test_non_inherited_outer_equals_lexical_outer(self, fixture_symbol: MixinSymbol) -> None:
        """For non-inherited symbols, outer and lexical_outer should be identical."""
        foo = fixture_symbol["Foo"]
        foo_bar = foo["Bar"]
        foo_bar_baz = foo_bar["Baz"]

        # At every level, outer == lexical_outer for non-inherited symbols
        assert foo.outer is foo.lexical_outer
        assert foo_bar.outer is foo_bar.lexical_outer
        assert foo_bar_baz.outer is foo_bar_baz.lexical_outer

    def test_qux_bar_outer_is_qux(self, fixture_symbol: MixinSymbol) -> None:
        """[Qux, Bar].outer should be [Qux] (structural parent in the symbol tree)."""
        qux = fixture_symbol["Qux"]
        qux_bar = qux["Bar"]

        assert isinstance(qux_bar.outer, MixinSymbol)
        assert qux_bar.outer is qux

    def test_qux_bar_lexical_outer_is_foo(self, fixture_symbol: MixinSymbol) -> None:
        """[Qux, Bar].lexical_outer should be [Foo] (where Bar's definition originates).

        Qux inherits [Foo], so Qux.Bar's definitions come from Foo.Bar.
        [Foo, Bar].lexical_outer is [Foo], so [Qux, Bar].lexical_outer should also be [Foo].
        """
        foo = fixture_symbol["Foo"]
        qux_bar = fixture_symbol["Qux"]["Bar"]

        assert isinstance(qux_bar.lexical_outer, MixinSymbol)
        assert qux_bar.lexical_outer is foo

    def test_qux_bar_baz_outer_is_qux_bar(self, fixture_symbol: MixinSymbol) -> None:
        """[Qux, Bar, Baz].outer should be [Qux, Bar] (structural parent)."""
        qux_bar = fixture_symbol["Qux"]["Bar"]
        qux_bar_baz = qux_bar["Baz"]

        assert isinstance(qux_bar_baz.outer, MixinSymbol)
        assert qux_bar_baz.outer is qux_bar

    def test_qux_bar_baz_lexical_outer_is_foo_bar(self, fixture_symbol: MixinSymbol) -> None:
        """[Qux, Bar, Baz].lexical_outer should be [Foo, Bar] (where Baz's definition originates).

        This is the key test from the user's specification.
        """
        foo_bar = fixture_symbol["Foo"]["Bar"]
        qux_bar_baz = fixture_symbol["Qux"]["Bar"]["Baz"]

        assert isinstance(qux_bar_baz.lexical_outer, MixinSymbol)
        assert qux_bar_baz.lexical_outer is foo_bar

    def test_inherited_outer_differs_from_lexical_outer(self, fixture_symbol: MixinSymbol) -> None:
        """For inherited symbols, outer and lexical_outer should differ."""
        qux_bar = fixture_symbol["Qux"]["Bar"]

        # outer is the structural parent (Qux)
        assert isinstance(qux_bar.outer, MixinSymbol)
        assert qux_bar.outer is fixture_symbol["Qux"]

        # lexical_outer is the definition origin (Foo)
        assert isinstance(qux_bar.lexical_outer, MixinSymbol)
        assert qux_bar.lexical_outer is fixture_symbol["Foo"]

        # They should NOT be the same
        assert qux_bar.outer is not qux_bar.lexical_outer


class TestMixinSymbolOuterIsomorphicWithMixin:
    """Test mixin.outer.symbol is mixin.symbol.outer."""

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

    def test_foo_bar_outer_isomorphism(self, fixture_scope: Scope) -> None:
        """mixin.outer.symbol is mixin.symbol.outer for non-inherited Foo.Bar."""
        foo_scope = fixture_scope.Foo
        assert isinstance(foo_scope, Scope)
        foo_bar_mixin = self._get_child_mixin(foo_scope, "Bar")

        assert isinstance(foo_bar_mixin.outer, Mixin)
        assert foo_bar_mixin.outer.symbol is foo_bar_mixin.symbol.outer

    def test_qux_bar_outer_isomorphism(self, fixture_scope: Scope) -> None:
        """mixin.outer.symbol is mixin.symbol.outer for inherited Qux.Bar."""
        qux_scope = fixture_scope.Qux
        assert isinstance(qux_scope, Scope)
        qux_bar_mixin = self._get_child_mixin(qux_scope, "Bar")

        assert isinstance(qux_bar_mixin.outer, Mixin)
        assert qux_bar_mixin.outer.symbol is qux_bar_mixin.symbol.outer

    def test_foo_bar_baz_outer_isomorphism(self, fixture_scope: Scope) -> None:
        """mixin.outer.symbol is mixin.symbol.outer for non-inherited Foo.Bar.Baz."""
        foo_scope = fixture_scope.Foo
        assert isinstance(foo_scope, Scope)
        foo_bar_scope = foo_scope.Bar
        assert isinstance(foo_bar_scope, Scope)
        foo_bar_baz_mixin = self._get_child_mixin(foo_bar_scope, "Baz")

        assert isinstance(foo_bar_baz_mixin.outer, Mixin)
        assert foo_bar_baz_mixin.outer.symbol is foo_bar_baz_mixin.symbol.outer

    def test_qux_bar_baz_outer_isomorphism(self, fixture_scope: Scope) -> None:
        """mixin.outer.symbol is mixin.symbol.outer for inherited Qux.Bar.Baz."""
        qux_scope = fixture_scope.Qux
        assert isinstance(qux_scope, Scope)
        qux_bar_scope = qux_scope.Bar
        assert isinstance(qux_bar_scope, Scope)
        qux_bar_baz_mixin = self._get_child_mixin(qux_bar_scope, "Baz")

        assert isinstance(qux_bar_baz_mixin.outer, Mixin)
        assert qux_bar_baz_mixin.outer.symbol is qux_bar_baz_mixin.symbol.outer


class TestMixinSymbolLexicalOuterIsomorphicWithMixin:
    """Test mixin.lexical_outer.symbol is mixin.symbol.lexical_outer."""

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

    def test_foo_bar_lexical_outer_isomorphism(self, fixture_scope: Scope) -> None:
        """mixin.lexical_outer.symbol is mixin.symbol.lexical_outer for non-inherited Foo.Bar."""
        foo_scope = fixture_scope.Foo
        assert isinstance(foo_scope, Scope)
        foo_bar_mixin = self._get_child_mixin(foo_scope, "Bar")

        assert isinstance(foo_bar_mixin.lexical_outer, Mixin)
        assert foo_bar_mixin.lexical_outer.symbol is foo_bar_mixin.symbol.lexical_outer

    @pytest.mark.xfail(
        reason="Known bug: Mixin._construct_scope sets lexical_outer=self for all children, "
        "including inherited ones. Should set lexical_outer to the base mixin for inherited children."
    )
    def test_qux_bar_lexical_outer_isomorphism(self, fixture_scope: Scope) -> None:
        """mixin.lexical_outer.symbol is mixin.symbol.lexical_outer for inherited Qux.Bar."""
        qux_scope = fixture_scope.Qux
        assert isinstance(qux_scope, Scope)
        qux_bar_mixin = self._get_child_mixin(qux_scope, "Bar")

        assert isinstance(qux_bar_mixin.lexical_outer, Mixin)
        assert qux_bar_mixin.lexical_outer.symbol is qux_bar_mixin.symbol.lexical_outer

    def test_foo_bar_baz_lexical_outer_isomorphism(self, fixture_scope: Scope) -> None:
        """mixin.lexical_outer.symbol is mixin.symbol.lexical_outer for non-inherited Foo.Bar.Baz."""
        foo_scope = fixture_scope.Foo
        assert isinstance(foo_scope, Scope)
        foo_bar_scope = foo_scope.Bar
        assert isinstance(foo_bar_scope, Scope)
        foo_bar_baz_mixin = self._get_child_mixin(foo_bar_scope, "Baz")

        assert isinstance(foo_bar_baz_mixin.lexical_outer, Mixin)
        assert foo_bar_baz_mixin.lexical_outer.symbol is foo_bar_baz_mixin.symbol.lexical_outer

    @pytest.mark.xfail(
        reason="Known bug: Mixin._construct_scope sets lexical_outer=self for all children, "
        "including inherited ones. Should set lexical_outer to the base mixin for inherited children."
    )
    def test_qux_bar_baz_lexical_outer_isomorphism(self, fixture_scope: Scope) -> None:
        """mixin.lexical_outer.symbol is mixin.symbol.lexical_outer for inherited Qux.Bar.Baz."""
        qux_scope = fixture_scope.Qux
        assert isinstance(qux_scope, Scope)
        qux_bar_scope = qux_scope.Bar
        assert isinstance(qux_bar_scope, Scope)
        qux_bar_baz_mixin = self._get_child_mixin(qux_bar_scope, "Baz")

        assert isinstance(qux_bar_baz_mixin.lexical_outer, Mixin)
        assert qux_bar_baz_mixin.lexical_outer.symbol is qux_bar_baz_mixin.symbol.lexical_outer

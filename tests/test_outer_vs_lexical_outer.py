"""Test that MixinSymbol.outer tracks structural parent correctly.

For an Overlay language structure like:
    Foo:
      Bar:
        Baz: []
    Qux:
      - [Foo]

[Qux, Bar, Baz].outer should be [Qux, Bar]  (structural parent in the symbol tree)
"""

from pathlib import Path

import pytest

from overlay.language import MixinSymbol
from overlay.language.mixin_directory import DirectoryMixinDefinition
from overlay.language.runtime import Mixin, Scope, evaluate


FIXTURES_PATH = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_symbol() -> MixinSymbol:
    """Load the OuterVsLexicalOuter fixture and return its MixinSymbol."""
    fixtures_definition = DirectoryMixinDefinition(
        inherits=(), is_public=True, underlying=FIXTURES_PATH
    )
    root = MixinSymbol(origin=(fixtures_definition,))
    return root["OuterVsLexicalOuter"]


class TestMixinSymbolOuter:
    """Test that MixinSymbol.outer returns the structural parent."""

    def test_foo_bar_baz_outer_is_foo_bar(self, fixture_symbol: MixinSymbol) -> None:
        """[Foo, Bar, Baz].outer should be [Foo, Bar]."""
        foo_bar = fixture_symbol["Foo"]["Bar"]
        foo_bar_baz = foo_bar["Baz"]

        assert isinstance(foo_bar_baz.outer, MixinSymbol)
        assert foo_bar_baz.outer is foo_bar

    def test_qux_bar_outer_is_qux(self, fixture_symbol: MixinSymbol) -> None:
        """[Qux, Bar].outer should be [Qux] (structural parent in the symbol tree)."""
        qux = fixture_symbol["Qux"]
        qux_bar = qux["Bar"]

        assert isinstance(qux_bar.outer, MixinSymbol)
        assert qux_bar.outer is qux

    def test_qux_bar_baz_outer_is_qux_bar(self, fixture_symbol: MixinSymbol) -> None:
        """[Qux, Bar, Baz].outer should be [Qux, Bar] (structural parent)."""
        qux_bar = fixture_symbol["Qux"]["Bar"]
        qux_bar_baz = qux_bar["Baz"]

        assert isinstance(qux_bar_baz.outer, MixinSymbol)
        assert qux_bar_baz.outer is qux_bar


class TestMixinSymbolOuterIsomorphicWithMixin:
    """Test mixin.outer.symbol is mixin.symbol.outer."""

    @pytest.fixture
    def fixture_scope(self) -> Scope:
        fixtures_definition = DirectoryMixinDefinition(
            inherits=(), is_public=True, underlying=FIXTURES_PATH
        )
        root_scope = evaluate(fixtures_definition, modules_public=True)
        result = root_scope.OuterVsLexicalOuter
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

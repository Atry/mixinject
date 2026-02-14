"""Tests for MixinSymbol and Definition classes (Symbol-level only, no V1 runtime)."""

import pytest

from overlay.language import (
    MixinSymbol,
    ObjectScopeDefinition,
    LexicalReference,
    FixtureReference,
)

L = LexicalReference
F = FixtureReference


def _make_scope_symbol(
    children: dict[str, "ObjectScopeDefinition"],
    bases: tuple = (),
) -> "ObjectScopeDefinition":
    """Create a ObjectScopeDefinition with specified child definitions."""

    class TestUnderlying:
        pass

    underlying = TestUnderlying()
    for key, child_def in children.items():
        setattr(underlying, key, child_def)
    return ObjectScopeDefinition(bases=bases, is_public=False, underlying=underlying)


class TestResolvedBases:
    """Test resolved_bases behavior for root symbols."""

    def test_root_symbol_with_empty_bases_returns_empty_tuple(self) -> None:
        """Root symbol with empty bases should return empty tuple."""
        scope_def = ObjectScopeDefinition(bases=(), is_public=False, underlying=object())
        root_symbol = MixinSymbol(origin=(scope_def,))
        assert root_symbol.normalized_references == ()


class TestLexicalReference:
    """Test LexicalReference resolution following the Overlay language spec."""

    def test_property_found_returns_full_path(self) -> None:
        """LexicalReference finds property in outer scope, returns full path."""
        # Structure: root_symbol contains "target" as a child, target contains "foo"
        # inner_symbol references L(path=("target", "foo"))
        foo_def = ObjectScopeDefinition(bases=(), is_public=False, underlying=object())
        target_def = _make_scope_symbol({"foo": foo_def})
        inner_def = ObjectScopeDefinition(
            bases=(L(path=("target", "foo")),),
            is_public=False,
            underlying=object(),
        )
        root_def = _make_scope_symbol({"target": target_def, "inner": inner_def})
        root_symbol = MixinSymbol(origin=(root_def,))

        # Get inner_symbol via parent (this ensures proper Nested resolution)
        inner_symbol = root_symbol["inner"]

        # "target" is found as property → full path returned
        resolved_bases = inner_symbol.normalized_references
        assert len(resolved_bases) == 1
        assert resolved_bases[0].de_bruijn_index == 0
        assert resolved_bases[0].path == ("target", "foo")

    def test_lexical_reference_not_found_raises_lookup_error(self) -> None:
        """LexicalReference raises LookupError when first segment not found."""
        inner_def = ObjectScopeDefinition(
            bases=(L(path=("nonexistent",)),),
            is_public=False,
            underlying=object(),
        )
        root_def = _make_scope_symbol({"inner": inner_def})
        root_symbol = MixinSymbol(origin=(root_def,))
        inner_symbol = root_symbol["inner"]
        with pytest.raises(LookupError, match="LexicalReference.*nonexistent.*not found"):
            _ = inner_symbol.normalized_references

    def test_lexical_reference_empty_path_raises_value_error(self) -> None:
        """LexicalReference with empty path raises ValueError."""
        inner_def = ObjectScopeDefinition(
            bases=(L(path=()),),
            is_public=False,
            underlying=object(),
        )
        root_def = _make_scope_symbol({"inner": inner_def})
        root_symbol = MixinSymbol(origin=(root_def,))
        inner_symbol = root_symbol["inner"]
        with pytest.raises(ValueError, match="LexicalReference path must not be empty"):
            _ = inner_symbol.normalized_references


class TestFixtureReference:
    """Test FixtureReference with pytest fixture-style same-name skip semantics."""

    def test_fixture_reference_not_found_raises_lookup_error(self) -> None:
        """FixtureReference raises LookupError when name not found."""
        inner_def = ObjectScopeDefinition(
            bases=(F(name="nonexistent"),),
            is_public=False,
            underlying=object(),
        )
        root_def = _make_scope_symbol({"inner": inner_def})
        root_symbol = MixinSymbol(origin=(root_def,))
        inner_symbol = root_symbol["inner"]
        with pytest.raises(LookupError, match="FixtureReference.*nonexistent.*not found"):
            _ = inner_symbol.normalized_references

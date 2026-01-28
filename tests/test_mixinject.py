"""Tests for MixinSymbol and Definition classes (Symbol-level only, no V1 runtime)."""

import pytest

from mixinject import (
    MixinSymbol,
    ScopeDefinition,
    LexicalReference,
    FixtureReference,
)

L = LexicalReference
F = FixtureReference


def _make_scope_symbol(
    children: dict[str, "ScopeDefinition"],
    bases: tuple = (),
) -> "ScopeDefinition":
    """Create a ScopeDefinition with specified child definitions."""

    class TestUnderlying:
        pass

    underlying = TestUnderlying()
    for key, child_def in children.items():
        setattr(underlying, key, child_def)
    return ScopeDefinition(bases=bases, underlying=underlying)


class TestResolvedBases:
    """Test resolved_bases behavior for root symbols."""

    def test_root_symbol_with_empty_bases_returns_empty_tuple(self) -> None:
        """Root symbol with empty bases should return empty tuple."""
        scope_def = ScopeDefinition(bases=(), underlying=object())
        root_symbol = MixinSymbol(origin=(scope_def,))
        assert root_symbol.resolved_bases == ()


class TestLexicalReference:
    """Test LexicalReference resolution following MIXIN spec."""

    def test_property_found_returns_full_path(self) -> None:
        """LexicalReference finds property in outer scope, returns full path."""
        # Structure: root_symbol contains "target" as a child, target contains "foo"
        # inner_symbol references L(path=("target", "foo"))
        foo_def = ScopeDefinition(bases=(), underlying=object())
        target_def = _make_scope_symbol({"foo": foo_def})
        inner_def = ScopeDefinition(
            underlying=object(),
            bases=(L(path=("target", "foo")),),
        )
        root_def = _make_scope_symbol({"target": target_def, "inner": inner_def})
        root_symbol = MixinSymbol(origin=(root_def,))

        # Get inner_symbol via parent (this ensures proper Nested resolution)
        inner_symbol = root_symbol["inner"]

        # "target" is found as property → full path returned
        resolved_bases = inner_symbol.resolved_bases
        assert len(resolved_bases) == 1
        assert resolved_bases[0].levels_up == 0
        assert resolved_bases[0].path == ("target", "foo")

    def test_self_reference_returns_rest_of_path(self) -> None:
        """LexicalReference with self-reference (path[0] == outer.key) returns path[1:].

        When path[0] matches the outer symbol's key but is NOT a property,
        this is a self-reference and we skip the first segment.
        """
        # Structure: root_symbol -> middle_symbol (key="Middle") -> inner_symbol
        # middle_symbol contains "foo" as a child
        # inner_symbol references L(path=("Middle", "foo"))
        # "Middle" is NOT a property of middle_symbol, but IS middle_symbol's key
        foo_def = ScopeDefinition(bases=(), underlying=object())
        inner_def = ScopeDefinition(
            underlying=object(),
            bases=(L(path=("Middle", "foo")),),
        )
        middle_def = _make_scope_symbol({"inner": inner_def, "foo": foo_def})
        root_def = _make_scope_symbol({"Middle": middle_def})
        root_symbol = MixinSymbol(origin=(root_def,))

        middle_symbol = root_symbol["Middle"]
        inner_symbol = middle_symbol["inner"]

        # At level 0: outer_symbol = middle_symbol
        # - "Middle" in middle_symbol? NO (Middle doesn't contain itself as property)
        # - "Middle" == middle_symbol.key? YES → self-reference
        # → ResolvedReference(levels_up=0, path=("foo",))
        resolved_bases = inner_symbol.resolved_bases
        assert len(resolved_bases) == 1
        assert resolved_bases[0].levels_up == 0
        assert resolved_bases[0].path == ("foo",)

    def test_self_reference_at_deeper_level(self) -> None:
        """Self-reference check happens at each level, not just the first."""
        # Structure: root (key=ROOT) -> A (key="A") -> B (key="B") -> inner
        # A contains "foo" as a child
        # inner references L(path=("A", "foo"))
        # A is NOT a property of B, and "A" != B.key
        # A is NOT a property of A, but "A" == A.key → self-reference at level 1
        foo_def = ScopeDefinition(bases=(), underlying=object())
        inner_def = ScopeDefinition(
            underlying=object(),
            bases=(L(path=("A", "foo")),),
        )
        b_def = _make_scope_symbol({"inner": inner_def})
        a_def = _make_scope_symbol({"B": b_def, "foo": foo_def})
        root_def = _make_scope_symbol({"A": a_def})
        root_symbol = MixinSymbol(origin=(root_def,))

        a_symbol = root_symbol["A"]
        b_symbol = a_symbol["B"]
        inner_symbol = b_symbol["inner"]

        # Level 0: outer_symbol = b_symbol
        # - "A" in b_symbol? NO
        # - "A" == b_symbol.key ("B")? NO
        # Level 1: outer_symbol = a_symbol
        # - "A" in a_symbol? NO (note: "A" != "foo", "B")
        # - "A" == a_symbol.key ("A")? YES → self-reference
        # → ResolvedReference(levels_up=1, path=("foo",))
        resolved_bases = inner_symbol.resolved_bases
        assert len(resolved_bases) == 1
        assert resolved_bases[0].levels_up == 1
        assert resolved_bases[0].path == ("foo",)

    def test_ambiguous_property_and_self_reference_raises_value_error(self) -> None:
        """Ambiguous reference raises ValueError.

        When a scope has key "A" AND contains a property "A", this is ambiguous
        and raises ValueError to preserve future compatibility.
        """
        # Structure: root_symbol -> A (key="A", contains property "A") -> inner
        # A also contains a property named "A" (ambiguous with self-reference)
        child_a_def = ScopeDefinition(bases=(), underlying=object())
        inner_def = ScopeDefinition(
            underlying=object(),
            bases=(L(path=("A", "bar")),),
        )
        a_def = _make_scope_symbol({"A": child_a_def, "inner": inner_def})
        root_def = _make_scope_symbol({"A": a_def})
        root_symbol = MixinSymbol(origin=(root_def,))

        a_symbol = root_symbol["A"]
        inner_symbol = a_symbol["inner"]

        # Level 0: outer_symbol = a_symbol
        # - "A" in a_symbol? YES
        # - "A" == a_symbol.key? YES
        # → Ambiguous! Raises ValueError
        with pytest.raises(ValueError, match="Ambiguous LexicalReference"):
            _ = inner_symbol.resolved_bases

    def test_lexical_reference_not_found_raises_lookup_error(self) -> None:
        """LexicalReference raises LookupError when first segment not found."""
        inner_def = ScopeDefinition(
            underlying=object(),
            bases=(L(path=("nonexistent",)),),
        )
        root_def = _make_scope_symbol({"inner": inner_def})
        root_symbol = MixinSymbol(origin=(root_def,))
        inner_symbol = root_symbol["inner"]
        with pytest.raises(LookupError, match="LexicalReference.*nonexistent.*not found"):
            _ = inner_symbol.resolved_bases

    def test_lexical_reference_empty_path_raises_value_error(self) -> None:
        """LexicalReference with empty path raises ValueError."""
        inner_def = ScopeDefinition(
            underlying=object(),
            bases=(L(path=()),),
        )
        root_def = _make_scope_symbol({"inner": inner_def})
        root_symbol = MixinSymbol(origin=(root_def,))
        inner_symbol = root_symbol["inner"]
        with pytest.raises(ValueError, match="LexicalReference path must not be empty"):
            _ = inner_symbol.resolved_bases


class TestFixtureReference:
    """Test FixtureReference with pytest fixture-style same-name skip semantics."""

    def test_fixture_reference_not_found_raises_lookup_error(self) -> None:
        """FixtureReference raises LookupError when name not found."""
        inner_def = ScopeDefinition(
            underlying=object(),
            bases=(F(name="nonexistent"),),
        )
        root_def = _make_scope_symbol({"inner": inner_def})
        root_symbol = MixinSymbol(origin=(root_def,))
        inner_symbol = root_symbol["inner"]
        with pytest.raises(LookupError, match="FixtureReference.*nonexistent.*not found"):
            _ = inner_symbol.resolved_bases

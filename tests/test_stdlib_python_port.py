"""Port of stdlib.oyaml to Python API to test resource/scope semantics.

Convention tested:
- Names starting with `_` → private (no @public decorator)
- Other names → public (@public decorator)
"""

import pytest

from overlay.language import (
    public,
    resource,
    scope,
    RelativeReference as R,
    extend,
    extern,
    MixinSymbol,
)
from overlay.language.runtime import Scope, evaluate


# =============================================================================
# Simple test: underscore prefix determines privacy
# =============================================================================


@scope
class TestPrivacy:
    """Test that underscore prefix determines privacy."""

    @public
    @scope
    class PublicScope:
        """Public scope (no underscore)."""

        pass

    @scope
    class _PrivateScope:
        """Private scope (underscore prefix)."""

        pass

    @public
    @resource
    def public_resource() -> str:
        """Public resource (no underscore)."""
        return "public"

    @resource
    def _private_resource() -> str:
        """Private resource (underscore prefix)."""
        return "private"


def test_public_scope_accessible():
    """Public scopes should be accessible via attribute."""
    root = evaluate(TestPrivacy)
    assert hasattr(root, "PublicScope")
    _ = root.PublicScope  # Should not raise


def test_private_scope_not_accessible():
    """Private scopes (underscore prefix) should not be accessible via attribute."""
    root = evaluate(TestPrivacy)
    with pytest.raises(AttributeError):
        _ = root._PrivateScope


def test_public_resource_accessible():
    """Public resources should be accessible via attribute."""
    root = evaluate(TestPrivacy)
    assert root.public_resource == "public"


def test_private_resource_not_accessible():
    """Private resources (underscore prefix) should not be accessible via attribute."""
    root = evaluate(TestPrivacy)
    with pytest.raises(AttributeError):
        _ = root._private_resource


def test_private_resource_accessible_as_dependency():
    """Private resources should be accessible as dependencies to other resources."""

    @scope
    class TestDependency:
        @resource
        def _private() -> str:
            return "private_value"

        @public
        @resource
        def public_consumer(_private: str) -> str:
            return f"consumed: {_private}"

    root = evaluate(TestDependency)
    assert root.public_consumer == "consumed: private_value"


# =============================================================================
# Port a simplified version of Nat
# =============================================================================


@public
@scope
class Nat:
    """Natural number type using Church encoding."""

    @public
    @scope
    class Zero:
        """Church encoding of zero."""

        @public
        @scope
        class Visitors:
            """Visitor pattern for Zero."""

            @public
            @scope
            class ZeroVisitor:
                """Handler for zero case."""

                pass

            @public
            @extend(R(de_bruijn_index=0, path=("ZeroVisitor",)))
            @scope
            class Visitor:
                """Result of visitor application (inherits from ZeroVisitor)."""

                pass

        @public
        @scope
        class Addition:
            """Addition operation for Zero: Zero + n = n."""

            @public
            @extern
            def addend() -> Scope:
                """The number to add (must be provided at instantiation)."""
                ...

            @public
            @resource
            def sum(addend: Scope) -> Scope:
                """Result of Zero + addend = addend."""
                # For Zero, adding anything just returns the addend
                return addend

    @public
    @scope
    class Succ:
        """Church encoding of successor (n + 1)."""

        @public
        @extern
        def predecessor() -> Scope:
            """The previous number (must be provided at instantiation)."""
            ...

        @public
        @scope
        class Visitors:
            """Visitor pattern for Succ."""

            @public
            @scope
            class SuccVisitor:
                """Handler for successor case."""

                pass

            @public
            @extend(R(de_bruijn_index=0, path=("SuccVisitor",)))
            @scope
            class Visitor:
                """Result of visitor application (inherits from SuccVisitor)."""

                pass

        @public
        @scope
        class Addition:
            """Addition operation for Succ: Succ(n) + m = Succ(n + m)."""

            @public
            @extern
            def addend() -> Scope:
                """The number to add (must be provided at instantiation)."""
                ...

            @resource
            def _increased_addend(addend: Scope, Succ: Scope) -> Scope:
                """Create Succ(addend)."""
                return Succ(predecessor=addend)

            @resource
            def _recursive_addition(
                predecessor: Scope, _increased_addend: Scope
            ) -> Scope:
                """Compute predecessor + Succ(addend)."""
                return predecessor.Addition(addend=_increased_addend)

            @public
            @resource
            def sum(_recursive_addition: Scope) -> Scope:
                """Result of Succ(n) + m = n + Succ(m)."""
                return _recursive_addition.sum


def test_nat_structure():
    """Test that Nat structure is accessible."""
    nat = evaluate(Nat)

    # All uppercase Scopes should be public and accessible
    assert hasattr(nat, "Zero")
    assert hasattr(nat, "Succ")

    zero = nat.Zero
    assert hasattr(zero, "Visitors")

    succ = nat.Succ
    assert hasattr(succ, "Visitors")


def test_zero_visitors_structure():
    """Test Zero's visitor pattern structure."""
    nat = evaluate(Nat)
    zero_visitors = nat.Zero.Visitors

    assert hasattr(zero_visitors, "ZeroVisitor")
    assert hasattr(zero_visitors, "Visitor")

    # Visitor should inherit from ZeroVisitor
    # (This is expressed via @extend in the definition)


def test_succ_visitors_structure():
    """Test Succ's visitor pattern structure."""
    nat = evaluate(Nat)
    succ_visitors = nat.Succ.Visitors

    assert hasattr(succ_visitors, "SuccVisitor")
    assert hasattr(succ_visitors, "Visitor")


# =============================================================================
# Test concrete Church numerals and addition
# =============================================================================


def count_church_numeral(num: Scope) -> int:
    """Count the depth of a Church numeral by following predecessor chain."""
    depth = 0
    current = num
    while hasattr(current, "predecessor"):
        depth += 1
        current = current.predecessor
    return depth


def test_zero_addition():
    """Test Zero + n = n."""
    nat = evaluate(Nat)

    # Create Zero
    zero = nat.Zero

    # Create One = Succ(Zero)
    one = nat.Succ(predecessor=zero)

    # Test: Zero + One = One
    zero_addition = zero.Addition(addend=one)
    result = zero_addition.sum

    # Result should be One (depth 1)
    assert count_church_numeral(result) == 1


def test_one_plus_zero():
    """Test One + Zero = One."""
    nat = evaluate(Nat)

    # Create Zero and One
    zero = nat.Zero
    one = nat.Succ(predecessor=zero)

    # Test: One + Zero = One
    one_addition = one.Addition(addend=zero)
    result = one_addition.sum

    # Result should be One (depth 1)
    assert count_church_numeral(result) == 1


def test_one_plus_one():
    """Test One + One = Two.

    BUG: Current runtime doesn't allow creating instances from scopes within instances.
    This test is written correctly but will fail until runtime is fixed.
    """
    nat = evaluate(Nat)

    # Create Zero, One
    zero = nat.Zero
    one = nat.Succ(predecessor=zero)

    # Test: One + One = Two
    # BUG: This line will fail with "TypeError: Cannot create instance from an instance scope"
    # because one.Addition is part of instance 'one', and calling __call__ on it is blocked
    one_addition = one.Addition(addend=one)
    result = one_addition.sum

    # Result should be Two (depth 2)
    assert count_church_numeral(result) == 2


def test_two_plus_three():
    """Test Two + Three = Five.

    BUG: Current runtime doesn't allow creating instances from scopes within instances.
    This test is written correctly but will fail until runtime is fixed.
    """
    nat = evaluate(Nat)

    # Build numerals
    zero = nat.Zero
    one = nat.Succ(predecessor=zero)
    two = nat.Succ(predecessor=one)
    three = nat.Succ(predecessor=two)

    # Test: Two + Three = Five
    # BUG: two.Addition(addend=three) will fail
    two_addition = two.Addition(addend=three)
    result = two_addition.sum

    # Result should be Five (depth 5)
    assert count_church_numeral(result) == 5


def test_three_plus_four():
    """Test Three + Four = Seven.

    BUG: Current runtime doesn't allow creating instances from scopes within instances.
    This test is written correctly but will fail until runtime is fixed.
    """
    nat = evaluate(Nat)

    # Build numerals
    zero = nat.Zero
    one = nat.Succ(predecessor=zero)
    two = nat.Succ(predecessor=one)
    three = nat.Succ(predecessor=two)
    four = nat.Succ(predecessor=three)

    # Test: Three + Four = Seven
    # BUG: three.Addition(addend=four) will fail
    three_addition = three.Addition(addend=four)
    result = three_addition.sum

    # Result should be Seven (depth 7)
    assert count_church_numeral(result) == 7


# =============================================================================
# Test symbol tree termination (compilation halts)
# =============================================================================


def traverse_symbol_tree_impl(
    symbol: "MixinSymbol",  # type: ignore
    visited: set[int],
    key_path: tuple[str, ...] = (),
    max_depth: int = 50,
    current_depth: int = 0,
) -> int:
    """Traverse symbol tree and count unique symbols.

    This traverses the compile-time Symbol structure, NOT the runtime Mixin instances.
    Does not trigger resource evaluation or Mixin creation.

    Args:
        symbol: Starting symbol
        visited: Set of visited symbol IDs (by id())
        key_path: Current path through the tree
        max_depth: Maximum traversal depth to prevent infinite loops
        current_depth: Current depth in traversal

    Returns:
        Number of unique symbols visited

    Raises:
        RecursionError: If max_depth is exceeded (indicates infinite tree)
    """
    if current_depth > max_depth:
        path_str = ".".join(key_path)
        raise RecursionError(
            f"Symbol tree depth exceeded {max_depth} at path: {path_str}"
        )

    symbol_id = id(symbol)
    if symbol_id in visited:
        return 0  # Already visited, don't count again

    visited.add(symbol_id)
    count = 1  # Count current symbol

    # Traverse all children in the symbol (compile-time structure)
    # Iterate over all children, including private ones
    for child_key in symbol.keys():
        child_symbol = symbol.get(child_key)
        if child_symbol is None:
            continue

        # Recursively traverse child (include both public and private)
        child_path = key_path + (str(child_key),)
        count += traverse_symbol_tree_impl(
            child_symbol,
            visited,
            child_path,
            max_depth,
            current_depth + 1,
        )

    return count


def traverse_symbol_tree(
    scope: Scope,
    visited: set[int],
    key_path: tuple[str, ...] = (),
    max_depth: int = 50,
    current_depth: int = 0,
) -> int:
    """Traverse symbol tree starting from a Scope.

    Wrapper that extracts the symbol and delegates to traverse_symbol_tree_impl.
    """
    return traverse_symbol_tree_impl(
        scope.symbol, visited, key_path, max_depth, current_depth
    )


def test_nat_symbol_tree_terminates():
    """Test that Nat symbol tree has finite depth.

    This ensures compilation terminates and doesn't generate infinite symbol trees.
    """
    nat = evaluate(Nat)

    visited: set[int] = set()
    node_count = traverse_symbol_tree(nat, visited, max_depth=50)

    # Verify traversal completed without hitting max depth
    assert node_count > 0, "Nat should have at least some symbols"

    # Verify tree is reasonably sized (not infinite)
    # Nat has: Zero, Succ, their Visitors, Additions, etc.
    # Should be < 100 unique symbols
    assert (
        node_count < 100
    ), f"Nat tree too large ({node_count} symbols), may be infinite"

    print(f"Nat symbol tree: {node_count} unique symbols (finite ✓)")


def test_zero_addition_symbol_tree_terminates():
    """Test that Zero.Addition symbol tree terminates."""
    nat = evaluate(Nat)
    zero = nat.Zero
    addition = zero.Addition

    visited: set[int] = set()
    node_count = traverse_symbol_tree(addition, visited, max_depth=50)

    assert node_count > 0, "Addition should have symbols"
    assert node_count < 50, f"Addition tree too large ({node_count} symbols)"

    print(f"Zero.Addition symbol tree: {node_count} unique symbols (finite ✓)")


def test_succ_addition_symbol_tree_terminates():
    """Test that Succ.Addition symbol tree terminates."""
    nat = evaluate(Nat)
    succ = nat.Succ
    addition = succ.Addition

    visited: set[int] = set()
    node_count = traverse_symbol_tree(addition, visited, max_depth=50)

    assert node_count > 0, "Addition should have symbols"
    assert node_count < 50, f"Addition tree too large ({node_count} symbols)"

    print(f"Succ.Addition symbol tree: {node_count} unique symbols (finite ✓)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

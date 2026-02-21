"""Tests for Cartesian product semantics of Plus on trie scopes.

A trie scope inherits multiple constructors simultaneously, so its pythonValues
returns a frozenset of all represented values. When Plus operates on such a
trie, the sum should reflect all combinations — i.e. the Cartesian product of
the two operand sets, mapped through addition.

For example:
  (Zero ∪ Two) + Three         →  {0+3, 2+3}               = {3, 5}
  Three + (One ∪ Two)          →  {3+1, 3+2}               = {4, 5}
  (One ∪ Two) + (Three ∪ Four) →  {1+3, 1+4, 2+3, 2+4}    = {4, 5, 6}

BinNat trie scopes share the same `half` field, so valid combinations are:
  Zero ∪ Even(h)   →  {0, 2h}
  Odd(h) ∪ Even(h) →  {2h+1, 2h}
"""

from pathlib import Path

import pytest

import overlay.library
from overlay.language.mixin_directory import DirectoryMixinDefinition
from overlay.language.runtime import Scope, evaluate


TESTS_PATH = Path(__file__).parent


@pytest.fixture
def cartesian_scope() -> Scope:
    """Load and evaluate the Cartesian product test fixture."""
    tests_definition = DirectoryMixinDefinition(
        inherits=(), is_public=True, underlying=TESTS_PATH
    )
    root = evaluate(overlay.library, tests_definition, modules_public=True)
    result = root.CartesianProductTest
    assert isinstance(result, Scope)
    return result


# =============================================================================
# Nat trie construction sanity checks
# =============================================================================


class TestNatTrieConstruction:
    """Verify that Nat trie scopes produce the expected value sets."""

    def test_nat_zero_or_two(self, cartesian_scope: Scope) -> None:
        assert cartesian_scope.NatZeroOrTwo.pythonValues == frozenset({0, 2})

    def test_nat_one_or_two(self, cartesian_scope: Scope) -> None:
        assert cartesian_scope.NatOneOrTwo.pythonValues == frozenset({1, 2})

    def test_nat_three_or_four(self, cartesian_scope: Scope) -> None:
        assert cartesian_scope.NatThreeOrFour.pythonValues == frozenset({3, 4})


# =============================================================================
# Nat Cartesian product via Plus
# =============================================================================


class TestNatCartesianProduct:
    """Test that Plus computes the full Cartesian product on trie operands."""

    def test_trie_left_concrete_right(self, cartesian_scope: Scope) -> None:
        """(Zero ∪ Two) + Three  →  {0+3, 2+3} = {3, 5}"""
        assert cartesian_scope.NatZeroOrTwoPlusThree.sum.pythonValues == frozenset({3, 5})

    def test_concrete_left_trie_right(self, cartesian_scope: Scope) -> None:
        """Three + (One ∪ Two)  →  {3+1, 3+2} = {4, 5}"""
        assert cartesian_scope.NatThreePlusOneOrTwo.sum.pythonValues == frozenset({4, 5})

    def test_trie_left_trie_right(self, cartesian_scope: Scope) -> None:
        """(One ∪ Two) + (Three ∪ Four)  →  {1+3, 1+4, 2+3, 2+4} = {4, 5, 6}"""
        assert cartesian_scope.NatOneOrTwoPlusThreeOrFour.sum.pythonValues == frozenset({4, 5, 6})

    def test_result_equality_self(self, cartesian_scope: Scope) -> None:
        """{4,5,6} == {4,5,6}  →  {True, False}  (Cartesian product of equalities)"""
        assert cartesian_scope.NatResultEqualitySelf.equal.pythonValues == frozenset({True, False})


# =============================================================================
# BinNat trie construction sanity checks
# =============================================================================


class TestBinNatTrieConstruction:
    """Verify that BinNat trie scopes produce the expected value sets."""

    def test_bin_nat_zero_or_two(self, cartesian_scope: Scope) -> None:
        """Zero ∪ Even(One)  →  {0, 2}"""
        assert cartesian_scope.BinNatZeroOrTwo.pythonValues == frozenset({0, 2})

    def test_bin_nat_two_or_three(self, cartesian_scope: Scope) -> None:
        """Even(One) ∪ Odd(One)  →  {2, 3}"""
        assert cartesian_scope.BinNatTwoOrThree.pythonValues == frozenset({2, 3})

    def test_bin_nat_four_or_five(self, cartesian_scope: Scope) -> None:
        """Even(Two) ∪ Odd(Two)  →  {4, 5}"""
        assert cartesian_scope.BinNatFourOrFive.pythonValues == frozenset({4, 5})


# =============================================================================
# BinNat Cartesian product via Plus
# =============================================================================


class TestBinNatCartesianProduct:
    """Test that BinNat Plus computes the full Cartesian product on trie operands."""

    def test_trie_left_concrete_right(self, cartesian_scope: Scope) -> None:
        """(Zero ∪ Two) + Three  →  {0+3, 2+3} = {3, 5}"""
        assert cartesian_scope.BinNatZeroOrTwoPlusThree.sum.pythonValues == frozenset({3, 5})

    def test_concrete_left_trie_right(self, cartesian_scope: Scope) -> None:
        """Three + (Two ∪ Three)  →  {3+2, 3+3} = {5, 6}"""
        assert cartesian_scope.BinNatThreePlusTwoOrThree.sum.pythonValues == frozenset({5, 6})

    def test_trie_left_trie_right(self, cartesian_scope: Scope) -> None:
        """(Two ∪ Three) + (Four ∪ Five)  →  {2+4, 2+5, 3+4, 3+5} = {6, 7, 8}"""
        assert cartesian_scope.BinNatTwoOrThreePlusFourOrFive.sum.pythonValues == frozenset({6, 7, 8})

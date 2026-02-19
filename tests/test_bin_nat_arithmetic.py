"""Tests for binary natural number arithmetic and equality.

Tests the Overlay language definitions in BinNatArithmeticTest.oyaml which compose
BinNatPlus and BinNatEquality from Builtin.oyaml to verify:
- Binary numeral construction (Zero, Even, Odd)
- Increment operation
- Addition (Plus operation)
- Equality checking (Equal operation)

Uses ToPython FFI definitions to convert binary-encoded values to Python natives.
"""

from pathlib import Path

import pytest

import overlay.library
from overlay.language.mixin_directory import DirectoryMixinDefinition
from overlay.language.runtime import Scope, evaluate


TESTS_PATH = Path(__file__).parent


@pytest.fixture
def bin_nat_scope() -> Scope:
    """Load and evaluate the binary natural arithmetic test fixture."""
    tests_definition = DirectoryMixinDefinition(
        bases=(), is_public=True, underlying=TESTS_PATH
    )
    root = evaluate(overlay.library, tests_definition, modules_public=True)
    result = root.BinNatArithmeticTest
    assert isinstance(result, Scope)
    return result


# =============================================================================
# Binary numeral construction tests
# =============================================================================


class TestBinNatConstruction:
    """Test that binary natural numbers are constructed correctly."""

    def test_zero(self, bin_nat_scope: Scope) -> None:
        assert bin_nat_scope.Zero.pythonValues == frozenset({0})

    def test_one(self, bin_nat_scope: Scope) -> None:
        assert bin_nat_scope.One.pythonValues == frozenset({1})

    def test_two(self, bin_nat_scope: Scope) -> None:
        assert bin_nat_scope.Two.pythonValues == frozenset({2})

    def test_three(self, bin_nat_scope: Scope) -> None:
        assert bin_nat_scope.Three.pythonValues == frozenset({3})

    def test_four(self, bin_nat_scope: Scope) -> None:
        assert bin_nat_scope.Four.pythonValues == frozenset({4})

    def test_five(self, bin_nat_scope: Scope) -> None:
        assert bin_nat_scope.Five.pythonValues == frozenset({5})

    def test_six(self, bin_nat_scope: Scope) -> None:
        assert bin_nat_scope.Six.pythonValues == frozenset({6})

    def test_seven(self, bin_nat_scope: Scope) -> None:
        assert bin_nat_scope.Seven.pythonValues == frozenset({7})


# =============================================================================
# Increment tests
# =============================================================================


class TestIncrement:
    """Test the increment (successor) operation on binary naturals."""

    def test_increment_zero(self, bin_nat_scope: Scope) -> None:
        """increment(0) = 1"""
        assert bin_nat_scope.Zero.increment.pythonValues == frozenset({1})

    def test_increment_three(self, bin_nat_scope: Scope) -> None:
        """increment(3) = 4"""
        assert bin_nat_scope.Three.increment.pythonValues == frozenset({4})

    def test_increment_six(self, bin_nat_scope: Scope) -> None:
        """increment(6) = 7"""
        assert bin_nat_scope.Six.increment.pythonValues == frozenset({7})


# =============================================================================
# Addition tests
# =============================================================================


class TestAddition:
    """Test binary natural number addition via the Plus operation."""

    def test_three_plus_four(self, bin_nat_scope: Scope) -> None:
        """3 + 4 = 7"""
        assert bin_nat_scope.threePlusFour.sum.pythonValues == frozenset({7})

    def test_five_plus_two(self, bin_nat_scope: Scope) -> None:
        """5 + 2 = 7"""
        assert bin_nat_scope.fivePlusTwo.sum.pythonValues == frozenset({7})

    def test_zero_plus_three(self, bin_nat_scope: Scope) -> None:
        """0 + 3 = 3"""
        assert bin_nat_scope.zeroPlusThree.sum.pythonValues == frozenset({3})


# =============================================================================
# Direct equality tests (without addition)
# =============================================================================


class TestDirectEquality:
    """Test binary natural number equality via the Equal operation."""

    def test_zero_equals_zero(self, bin_nat_scope: Scope) -> None:
        """0 == 0 is True"""
        assert bin_nat_scope.zeroEqualsZero.equal.pythonValues == frozenset({True})

    def test_three_equals_three(self, bin_nat_scope: Scope) -> None:
        """3 == 3 is True"""
        assert bin_nat_scope.threeEqualsThree.equal.pythonValues == frozenset({True})

    def test_three_equals_four(self, bin_nat_scope: Scope) -> None:
        """3 == 4 is False"""
        assert bin_nat_scope.threeEqualsFour.equal.pythonValues == frozenset({False})


# =============================================================================
# Equality tests with addition results
# =============================================================================


class TestEqualityWithAddition:
    """Test equality of addition results."""

    def test_three_plus_four_equals_seven(self, bin_nat_scope: Scope) -> None:
        """(3 + 4) == 7 is True"""
        assert (
            bin_nat_scope.threePlusFourEqualsSeven.equal.pythonValues == frozenset({True})
        )

    def test_five_plus_two_equals_seven(self, bin_nat_scope: Scope) -> None:
        """(5 + 2) == 7 is True"""
        assert (
            bin_nat_scope.fivePlusTwoEqualsSeven.equal.pythonValues == frozenset({True})
        )

    def test_five_plus_two_equals_two(self, bin_nat_scope: Scope) -> None:
        """(5 + 2) == 2 is False"""
        assert bin_nat_scope.fivePlusTwoEqualsTwo.equal.pythonValues == frozenset({False})

    def test_zero_plus_three_equals_three(self, bin_nat_scope: Scope) -> None:
        """(0 + 3) == 3 is True"""
        assert (
            bin_nat_scope.zeroPlusThreeEqualsThree.equal.pythonValues == frozenset({True})
        )

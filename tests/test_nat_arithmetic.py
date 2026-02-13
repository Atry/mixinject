"""Tests for Church-encoded natural number arithmetic and equality.

Tests the OL definitions in ArithmeticTest.ol.yaml which compose
NatPlus and NatEquality from Builtin.ol.yaml to verify:
- Church numeral construction
- Addition (Plus operation)
- Equality checking (Equal operation)

Uses ToPython FFI definitions to convert Church-encoded values to Python natives.
"""

from pathlib import Path

import pytest

import overlay.library
from overlay.language.mixin_directory import DirectoryMixinDefinition
from overlay.language.runtime import Scope, evaluate


TESTS_PATH = Path(__file__).parent


@pytest.fixture
def arithmetic_scope() -> Scope:
    """Load and evaluate the arithmetic test fixture with stdlib and FFI."""
    tests_definition = DirectoryMixinDefinition(
        bases=(), is_public=True, underlying=TESTS_PATH
    )
    root = evaluate(overlay.library, tests_definition, modules_public=True)
    result = root.ArithmeticTest
    assert isinstance(result, Scope)
    return result


# =============================================================================
# Church numeral construction tests
# =============================================================================

class TestChurchNumerals:
    """Test that Church numerals are constructed correctly."""

    def test_zero(self, arithmetic_scope: Scope) -> None:
        assert arithmetic_scope.Zero.ToPython.pythonValue == 0

    def test_one(self, arithmetic_scope: Scope) -> None:
        assert arithmetic_scope.One.ToPython.pythonValue == 1

    def test_two(self, arithmetic_scope: Scope) -> None:
        assert arithmetic_scope.Two.ToPython.pythonValue == 2

    def test_three(self, arithmetic_scope: Scope) -> None:
        assert arithmetic_scope.Three.ToPython.pythonValue == 3

    def test_four(self, arithmetic_scope: Scope) -> None:
        assert arithmetic_scope.Four.ToPython.pythonValue == 4

    def test_five(self, arithmetic_scope: Scope) -> None:
        assert arithmetic_scope.Five.ToPython.pythonValue == 5

    def test_six(self, arithmetic_scope: Scope) -> None:
        assert arithmetic_scope.Six.ToPython.pythonValue == 6

    def test_seven(self, arithmetic_scope: Scope) -> None:
        assert arithmetic_scope.Seven.ToPython.pythonValue == 7


# =============================================================================
# Addition tests
# =============================================================================


class TestAddition:
    """Test Church numeral addition via the Plus operation."""

    def test_three_plus_four(self, arithmetic_scope: Scope) -> None:
        """3 + 4 = 7"""
        assert arithmetic_scope.threePlusFour.sum.ToPython.pythonValue == 7

    def test_five_plus_two(self, arithmetic_scope: Scope) -> None:
        """5 + 2 = 7"""
        assert arithmetic_scope.fivePlusTwo.sum.ToPython.pythonValue == 7

    def test_zero_plus_three(self, arithmetic_scope: Scope) -> None:
        """0 + 3 = 3"""
        assert arithmetic_scope.zeroPlusThree.sum.ToPython.pythonValue == 3


# =============================================================================
# Direct equality tests (without addition)
# =============================================================================


class TestDirectEquality:
    """Test Church numeral equality via the Equal operation."""

    def test_zero_equals_zero(self, arithmetic_scope: Scope) -> None:
        """0 == 0 is True"""
        assert arithmetic_scope.zeroEqualsZero.equal.ToPython.pythonValue is True

    def test_three_equals_three(self, arithmetic_scope: Scope) -> None:
        """3 == 3 is True"""
        assert arithmetic_scope.threeEqualsThree.equal.ToPython.pythonValue is True

    def test_three_equals_four(self, arithmetic_scope: Scope) -> None:
        """3 == 4 is False"""
        assert arithmetic_scope.threeEqualsFour.equal.ToPython.pythonValue is False


# =============================================================================
# Equality tests with addition results
# =============================================================================


class TestEqualityWithAddition:
    """Test equality of addition results."""

    def test_three_plus_four_equals_seven(self, arithmetic_scope: Scope) -> None:
        """(3 + 4) == 7 is True"""
        assert (
            arithmetic_scope.threePlusFourEqualsSeven.equal.ToPython.pythonValue is True
        )

    def test_five_plus_two_equals_seven(self, arithmetic_scope: Scope) -> None:
        """(5 + 2) == 7 is True"""
        assert (
            arithmetic_scope.fivePlusTwoEqualsSeven.equal.ToPython.pythonValue is True
        )

    def test_five_plus_two_equals_two(self, arithmetic_scope: Scope) -> None:
        """(5 + 2) == 2 is False"""
        assert arithmetic_scope.fivePlusTwoEqualsTwo.equal.ToPython.pythonValue is False

    def test_zero_plus_three_equals_three(self, arithmetic_scope: Scope) -> None:
        """(0 + 3) == 3 is True"""
        assert (
            arithmetic_scope.zeroPlusThreeEqualsThree.equal.ToPython.pythonValue is True
        )

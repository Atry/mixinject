"""Tests for Church-encoded boolean equality via ANF translation rules.

Demonstrates the Felleisen expressiveness proof: eq(false, false) and
eq(true, true) both evaluate to Church true in L₀, but are distinguishable
in L₁ after overlaying additional definitions.

Church booleans are applied to Nat values (One, Zero) to observe results:
- Church true applied to (One, Zero) selects One → pythonValues = {1}
- Church false applied to (One, Zero) selects Zero → pythonValues = {0}
"""

from pathlib import Path

import pytest

import overlay.library
from overlay.language._mixin_directory import DirectoryMixinDefinition
from overlay.language._runtime import Scope, evaluate


TESTS_PATH = Path(__file__).parent


@pytest.fixture
def church_scope() -> Scope:
    """Load and evaluate the Church boolean test fixture."""
    tests_definition = DirectoryMixinDefinition(
        inherits=(), is_public=True, underlying=TESTS_PATH
    )
    root = evaluate(overlay.library, tests_definition, modules_public=True)
    result = root.ChurchBooleanTest
    assert isinstance(result, Scope)
    return result


# =============================================================================
# Church boolean construction tests
# =============================================================================


class TestChurchBooleanConstruction:
    """Verify Church true/false have the abstraction shape."""

    def test_church_true_has_argument(self, church_scope: Scope) -> None:
        assert hasattr(church_scope.ChurchTrue, "argument")

    def test_church_true_has_result(self, church_scope: Scope) -> None:
        assert hasattr(church_scope.ChurchTrue, "result")

    def test_church_false_has_argument(self, church_scope: Scope) -> None:
        assert hasattr(church_scope.ChurchFalse, "argument")

    def test_church_false_has_result(self, church_scope: Scope) -> None:
        assert hasattr(church_scope.ChurchFalse, "result")


# =============================================================================
# Church boolean observation tests (via application to Nat values)
# =============================================================================


class TestChurchBooleanObservation:
    """Verify Church true selects first arg, Church false selects second."""

    def test_church_true_selects_first(self, church_scope: Scope) -> None:
        """Church true applied to (One, Zero) should select One."""
        assert church_scope.churchTrueObserved.pythonValues == frozenset({1})

    def test_church_false_selects_second(self, church_scope: Scope) -> None:
        """Church false applied to (One, Zero) should select Zero."""
        assert church_scope.churchFalseObserved.pythonValues == frozenset({0})


# =============================================================================
# Church equality tests
# =============================================================================


class TestChurchEquality:
    """Verify eq(false,false) and eq(true,true) both produce Church true."""

    def test_false_eq_false_is_church_true(self, church_scope: Scope) -> None:
        """eq(false,false) should evaluate to Church true (selects One)."""
        assert church_scope.falseEqFalseObserved.pythonValues == frozenset({1})

    def test_true_eq_true_is_church_true(self, church_scope: Scope) -> None:
        """eq(true,true) should evaluate to Church true (selects One)."""
        assert church_scope.trueEqTrueObserved.pythonValues == frozenset({1})

    def test_both_equivalent_in_l0(self, church_scope: Scope) -> None:
        """Both eq results are observationally equivalent in L₀."""
        assert (
            church_scope.falseEqFalseObserved.pythonValues
            == church_scope.trueEqTrueObserved.pythonValues
        )


# =============================================================================
# Overlay C: distinguishability in L₁ (Felleisen Theorem 3.14)
#
# The overlay adds repr.firstOperand and repr.secondOperand to ChurchEq,
# reflecting both operands through the result chain. This makes eq(false,false)
# and eq(true,true) distinguishable even though both evaluate to Church true.
# =============================================================================


class TestOverlayDistinguishability:
    """Overlay C (repr) makes eq(false,false) and eq(true,true) distinguishable.

    In L₁ = L₀ + overlay, the repr scope reflects both operands of the
    equality test. This is impossible in λ-calculus: a function's result
    is closed and cannot gain new observable projections after definition.
    """

    def test_false_eq_false_repr_first_is_false(self, church_scope: Scope) -> None:
        """repr.firstOperand of eq(false,false) is ChurchFalse → selects Zero."""
        assert church_scope.falseEqFalseReprFirst.pythonValues == frozenset({0})

    def test_false_eq_false_repr_second_is_false(self, church_scope: Scope) -> None:
        """repr.secondOperand of eq(false,false) is ChurchFalse → selects Zero."""
        assert church_scope.falseEqFalseReprSecond.pythonValues == frozenset({0})

    def test_true_eq_true_repr_first_is_true(self, church_scope: Scope) -> None:
        """repr.firstOperand of eq(true,true) is ChurchTrue → selects One."""
        assert church_scope.trueEqTrueReprFirst.pythonValues == frozenset({1})

    def test_true_eq_true_repr_second_is_true(self, church_scope: Scope) -> None:
        """repr.secondOperand of eq(true,true) is ChurchTrue → selects One."""
        assert church_scope.trueEqTrueReprSecond.pythonValues == frozenset({1})

    def test_distinguishable_via_repr_first(self, church_scope: Scope) -> None:
        """eq(false,false) and eq(true,true) are distinguishable via repr.firstOperand."""
        assert (
            church_scope.falseEqFalseReprFirst.pythonValues
            != church_scope.trueEqTrueReprFirst.pythonValues
        )

    def test_distinguishable_via_repr_second(self, church_scope: Scope) -> None:
        """eq(false,false) and eq(true,true) are distinguishable via repr.secondOperand."""
        assert (
            church_scope.falseEqFalseReprSecond.pythonValues
            != church_scope.trueEqTrueReprSecond.pythonValues
        )

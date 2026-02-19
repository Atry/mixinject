"""Tests for generic Fibonacci on both Nat and BinNat.

Tests the abstract Fibonacci definition from Builtin/Fibonacci.oyaml,
instantiated with both Church numerals (Nat) and binary naturals (BinNat).
Verifies that both the direct double-recursion version and the
pair-accumulator version produce identical results.
"""

from pathlib import Path

import pytest

import overlay.library
from overlay.language.mixin_directory import DirectoryMixinDefinition
from overlay.language.runtime import Scope, evaluate


TESTS_PATH = Path(__file__).parent


@pytest.fixture
def fibonacci_scope() -> Scope:
    """Load and evaluate the Fibonacci test fixture."""
    tests_definition = DirectoryMixinDefinition(
        bases=(), is_public=True, underlying=TESTS_PATH
    )
    root = evaluate(overlay.library, tests_definition, modules_public=True)
    result = root.FibonacciTest
    assert isinstance(result, Scope)
    return result


FIBONACCI_SEQUENCE = (0, 1, 1, 2, 3, 5, 8)
NAMES = ("Zero", "One", "Two", "Three", "Four", "Five", "Six")


class TestNatFibonacciDirect:
    """Test direct double-recursion Fibonacci on Nat."""

    @pytest.mark.parametrize(
        ("index", "expected"),
        tuple(zip(NAMES, FIBONACCI_SEQUENCE, strict=True)),
    )
    def test_fibonacci(
        self, fibonacci_scope: Scope, index: str, expected: int
    ) -> None:
        instance = getattr(fibonacci_scope, f"natFib{index}")
        assert instance.fibonacci.pythonValues == frozenset({expected})


class TestNatFibonacciAccumulator:
    """Test pair-accumulator Fibonacci on Nat."""

    @pytest.mark.parametrize(
        ("index", "expected"),
        tuple(zip(NAMES, FIBONACCI_SEQUENCE, strict=True)),
    )
    def test_fibonacci(
        self, fibonacci_scope: Scope, index: str, expected: int
    ) -> None:
        instance = getattr(fibonacci_scope, f"natFibAcc{index}")
        assert instance.fibonacci.pythonValues == frozenset({expected})


class TestBinNatFibonacciDirect:
    """Test direct double-recursion Fibonacci on BinNat."""

    @pytest.mark.parametrize(
        ("index", "expected"),
        tuple(zip(NAMES, FIBONACCI_SEQUENCE, strict=True)),
    )
    def test_fibonacci(
        self, fibonacci_scope: Scope, index: str, expected: int
    ) -> None:
        instance = getattr(fibonacci_scope, f"binNatFib{index}")
        assert instance.fibonacci.pythonValues == frozenset({expected})


class TestBinNatFibonacciAccumulator:
    """Test pair-accumulator Fibonacci on BinNat."""

    @pytest.mark.parametrize(
        ("index", "expected"),
        tuple(zip(NAMES, FIBONACCI_SEQUENCE, strict=True)),
    )
    def test_fibonacci(
        self, fibonacci_scope: Scope, index: str, expected: int
    ) -> None:
        instance = getattr(fibonacci_scope, f"binNatFibAcc{index}")
        assert instance.fibonacci.pythonValues == frozenset({expected})


class TestFibonacciConsistency:
    """Test that direct and accumulator versions produce identical results."""

    @pytest.mark.parametrize("index", NAMES)
    def test_nat_consistency(self, fibonacci_scope: Scope, index: str) -> None:
        direct = getattr(fibonacci_scope, f"natFib{index}")
        accumulator = getattr(fibonacci_scope, f"natFibAcc{index}")
        assert (
            direct.fibonacci.pythonValues
            == accumulator.fibonacci.pythonValues
        )

    @pytest.mark.parametrize("index", NAMES)
    def test_bin_nat_consistency(
        self, fibonacci_scope: Scope, index: str
    ) -> None:
        direct = getattr(fibonacci_scope, f"binNatFib{index}")
        accumulator = getattr(fibonacci_scope, f"binNatFibAcc{index}")
        assert (
            direct.fibonacci.pythonValues
            == accumulator.fibonacci.pythonValues
        )

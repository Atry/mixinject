"""Tests for Cartesian product semantics of Fibonacci on trie scopes.

When n is a trie scope representing multiple values simultaneously, ideally
Fibonacci would compute fib for each value independently:
  n ∈ {2, 3}  →  fibonacci ∈ {fib(2), fib(3)} = {1, 2}

However, both the direct and accumulator Fibonacci algorithms use conditional
dispatch (IsZero, IsOne) that is not Cartesian-product-safe. With trie n,
all branches of each conditional fire simultaneously, producing spurious
intermediate values that propagate through the recursion via Cartesian product
of Plus. As a result, the output set is a superset of the ideal result.

Observed behaviour:
  Nat direct,       n ∈ {2, 3}  →  {0, 1, 2}          (ideal: {1, 2})
  Nat direct,       n ∈ {4, 5}  →  {0, 1, 2, 3, 4, 5} (ideal: {3, 5})
  Nat accumulator,  n ∈ {2, 3}  →  {1, 2}              (ideal: {1, 2}) ✓
  Nat accumulator,  n ∈ {4, 5}  →  {3, 4, 5}           (ideal: {3, 5})
  BinNat direct,    n ∈ {2, 3}  →  {0, 1, 2}           (ideal: {1, 2})
  BinNat direct,    n ∈ {4, 5}  →  {0..10}             (ideal: {3, 5})
  BinNat accumulator, n ∈ {2,3} →  {1, 2}              (ideal: {1, 2}) ✓
  BinNat accumulator, n ∈ {4,5} →  {0..10}             (ideal: {3, 5})

The accumulator variant behaves better for small inputs because its linear
recursion produces fewer spurious branches, but it still fails for larger
inputs where the intermediate _next and _current values accumulate extra paths.
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
        inherits=(), is_public=True, underlying=TESTS_PATH
    )
    root = evaluate(overlay.library, tests_definition, modules_public=True)
    result = root.FibonacciTest
    assert isinstance(result, Scope)
    return result


# =============================================================================
# Nat trie Fibonacci: direct double-recursion
# Produces a superset of ideal results due to branch merging in IsZero/IsOne.
# =============================================================================


class TestNatFibonacciDirectTrie:
    """Nat direct Fibonacci with trie n: produces a superset of ideal results."""

    def test_two_or_three(self, fibonacci_scope: Scope) -> None:
        """n ∈ {2, 3}  →  {0, 1, 2} (ideal: {1, 2}; spurious: 0)"""
        assert fibonacci_scope.natFibTwoOrThree.fibonacci.pythonValues == frozenset({0, 1, 2})

    def test_four_or_five(self, fibonacci_scope: Scope) -> None:
        """n ∈ {4, 5}  →  {0,1,2,3,4,5} (ideal: {3, 5}; many spurious values)"""
        assert fibonacci_scope.natFibFourOrFive.fibonacci.pythonValues == frozenset({0, 1, 2, 3, 4, 5})


# =============================================================================
# Nat trie Fibonacci: pair-accumulator
# Better for small inputs, but still fails for larger ones.
# =============================================================================


class TestNatFibonacciAccumulatorTrie:
    """Nat accumulator Fibonacci with trie n: correct for {2,3}, superset for {4,5}."""

    def test_two_or_three(self, fibonacci_scope: Scope) -> None:
        """n ∈ {2, 3}  →  {1, 2} (ideal: {1, 2}) ✓"""
        assert fibonacci_scope.natFibAccTwoOrThree.fibonacci.pythonValues == frozenset({1, 2})

    def test_four_or_five(self, fibonacci_scope: Scope) -> None:
        """n ∈ {4, 5}  →  {3, 4, 5} (ideal: {3, 5}; spurious: 4)"""
        assert fibonacci_scope.natFibAccFourOrFive.fibonacci.pythonValues == frozenset({3, 4, 5})


# =============================================================================
# BinNat trie Fibonacci: direct double-recursion
# =============================================================================


class TestBinNatFibonacciDirectTrie:
    """BinNat direct Fibonacci with trie n: produces a superset of ideal results."""

    def test_two_or_three(self, fibonacci_scope: Scope) -> None:
        """n ∈ {2, 3}  →  {0, 1, 2} (ideal: {1, 2}; spurious: 0)"""
        assert fibonacci_scope.binNatFibTwoOrThree.fibonacci.pythonValues == frozenset({0, 1, 2})

    def test_four_or_five(self, fibonacci_scope: Scope) -> None:
        """n ∈ {4, 5}  →  {0..10} (ideal: {3, 5}; many spurious values)"""
        assert fibonacci_scope.binNatFibFourOrFive.fibonacci.pythonValues == frozenset(range(11))


# =============================================================================
# BinNat trie Fibonacci: pair-accumulator
# =============================================================================


class TestBinNatFibonacciAccumulatorTrie:
    """BinNat accumulator Fibonacci with trie n: correct for {2,3}, poor for {4,5}."""

    def test_two_or_three(self, fibonacci_scope: Scope) -> None:
        """n ∈ {2, 3}  →  {1, 2} (ideal: {1, 2}) ✓"""
        assert fibonacci_scope.binNatFibAccTwoOrThree.fibonacci.pythonValues == frozenset({1, 2})

    def test_four_or_five(self, fibonacci_scope: Scope) -> None:
        """n ∈ {4, 5}  →  {0..10} (ideal: {3, 5}; many spurious values)"""
        assert fibonacci_scope.binNatFibAccFourOrFive.fibonacci.pythonValues == frozenset(range(11))

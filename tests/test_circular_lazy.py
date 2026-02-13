"""Test circular references with lazy evaluation.

This test demonstrates that with lazy evaluation, MIXIN can support circular
references while remaining total. Each finite access terminates, even though
the conceptual structure is infinite.

This is similar to Haskell's "tying the knot" technique or Coq's coinductive types.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from overlay.language.mixin_parser import parse_mixin_file
from overlay.language.runtime import evaluate


def test_circular_reference_parsing():
    """Test that circular reference MIXIN file can be parsed."""
    fixture_path = Path(__file__).parent / "fixtures" / "circular_lazy.ol.yaml"
    parsed = parse_mixin_file(fixture_path)

    # Should have three top-level mixins
    assert "Tuple1" in parsed
    assert "foo" in parsed
    assert "bar" in parsed


@pytest.mark.skip(
    reason="Lazy evaluation not yet implemented - will enable after naming convention detection is added"
)
def test_circular_reference_lazy_evaluation():
    """Test circular references with lazy evaluation.

    Once lazy evaluation is implemented (via naming convention detection):
    - foo and bar should form a circular reference
    - But each finite access should terminate
    - This demonstrates totality with circular references
    """
    fixture_path = Path(__file__).parent / "fixtures" / "circular_lazy.ol.yaml"
    parsed = parse_mixin_file(fixture_path)

    # Get the root definitions
    tuple1_defs = parsed["Tuple1"]
    foo_defs = parsed["foo"]
    bar_defs = parsed["bar"]

    # Evaluate Tuple1 (should be a scope)
    assert len(tuple1_defs) == 1
    tuple1 = evaluate(tuple1_defs[0])

    # Evaluate foo and bar (should be resources with lazy evaluation)
    assert len(foo_defs) == 1
    assert len(bar_defs) == 1

    foo = evaluate(foo_defs[0])
    bar = evaluate(bar_defs[0])

    # Test circular reference with finite accesses
    # Each access should terminate despite the cycle

    # Access depth 1: foo._1 should be bar
    assert foo._1 is bar

    # Access depth 2: bar._1 should be foo
    assert bar._1 is foo

    # Access depth 3: foo._1._1 should be foo (cycle detected)
    assert foo._1._1 is foo

    # Access depth 4: bar._1._1 should be bar (cycle detected)
    assert bar._1._1 is bar

    # Access depth 5: traversing the cycle
    assert foo._1._1._1 is bar
    assert foo._1._1._1._1 is foo

    # All accesses terminated successfully!
    # This demonstrates totality: the program never gets stuck,
    # even with circular references


@pytest.mark.skip(
    reason="Eager evaluation causes infinite loop - demonstrates why lazy evaluation is needed"
)
def test_circular_reference_eager_evaluation_fails():
    """Test that circular references fail with eager evaluation.

    With eager evaluation (current implementation), attempting to evaluate
    circular references would cause an infinite loop during construction.

    This test is skipped because it would hang the test suite, but it
    demonstrates why lazy evaluation is necessary for circular references.
    """
    fixture_path = Path(__file__).parent / "fixtures" / "circular_lazy.ol.yaml"
    parsed = parse_mixin_file(fixture_path)

    foo_defs = parsed["foo"]
    bar_defs = parsed["bar"]

    # With eager evaluation, this would hang:
    # foo = evaluate(foo_defs[0])
    # Because evaluating foo requires evaluating foo._1 which is bar,
    # and evaluating bar requires evaluating bar._1 which is foo,
    # creating an infinite loop.

    # This is why lazy evaluation is essential for supporting circular references


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

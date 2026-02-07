"""Test multi-module composition with overlapping class definitions.

Minimal reproduction for a known bug where Module3.Class4's inheritance chain
should contain all 6 non-synthetic MixinSymbol entries from Module1 and Module2.

Module1 defines: Class1, Class2 (2 definitions)
Module2 defines: Class1, Class2, Class3, Class4 (4 definitions)
Module3 inherits: [Module1], [Module2]

Through composition and inheritance chains, Module3.Class4 should transitively
reach all 6 original class definitions as distinct MixinSymbol objects.
"""

from pathlib import Path

import pytest

from mixinject import MixinSymbol
from mixinject.mixin_directory import DirectoryMixinDefinition
from mixinject.runtime import Scope, evaluate


FIXTURES_PATH = Path(__file__).parent / "fixtures"

CLASS_NAMES = frozenset({"Class1", "Class2", "Class3", "Class4"})


def _collect_all_super_symbols(symbol: MixinSymbol) -> set[MixinSymbol]:
    """Recursively collect all MixinSymbols in the inheritance chain (including self)."""
    collected: set[MixinSymbol] = set()

    def walk(current: MixinSymbol) -> None:
        if current in collected:
            return
        collected.add(current)
        for super_symbol in current.generate_strict_super():
            walk(super_symbol)

    walk(symbol)
    return collected


@pytest.fixture
def multi_module_scope() -> Scope:
    """Load and evaluate the multi-module composition fixture."""
    fixtures_definition = DirectoryMixinDefinition(
        bases=(), is_public=True, underlying=FIXTURES_PATH
    )
    root = evaluate(fixtures_definition, modules_public=True)
    result = root.multi_module_composition
    assert isinstance(result, Scope)
    return result


@pytest.mark.xfail(reason="Known bug: inheritance chain missing some non-synthetic MixinSymbols")
class TestMultiModuleComposition:
    """Test that Module3.Class4's super chain contains all 6 non-synthetic MixinSymbols."""

    def test_class4_super_chain_contains_all_classes(
        self, multi_module_scope: Scope
    ) -> None:
        module3 = multi_module_scope.Module3
        assert isinstance(module3, Scope)

        class4_symbol = module3.symbol["Class4"]
        all_symbols = _collect_all_super_symbols(class4_symbol)

        # Filter to non-synthetic symbols (keys matching original class names)
        non_synthetic = {
            symbol for symbol in all_symbols if symbol.key in CLASS_NAMES
        }

        # Should have at least 6 non-synthetic MixinSymbols:
        # From Module1: Class1, Class2 (2)
        # From Module2: Class1, Class2, Class3, Class4 (4)
        # Total: 6 distinct MixinSymbol objects
        assert len(non_synthetic) == 6

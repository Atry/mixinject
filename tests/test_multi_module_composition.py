"""Test multi-module composition with overlapping class definitions.

Tests scenarios:
1. Flat structure (reproduction of original bug).
2. Nested structure (reproduction of bug with nested scopes).
3. Diamond structure (composition reducing nesting depth).
4. Flatten structure (composition flattening multiple nesting levels).

All are minimal reproductions for known bugs where inheritance chains
should contain all non-synthetic MixinSymbol entries from constituent modules.
"""

from collections.abc import Hashable
from pathlib import Path
from typing import Any

import pytest

from syrupy.assertion import SnapshotAssertion

from overlay.language import MixinSymbol
from overlay.language.mixin_directory import DirectoryMixinDefinition
from overlay.language.runtime import Scope, evaluate


FIXTURES_PATH = Path(__file__).parent / "fixtures"

CLASS_NAMES = frozenset({"Class1", "Class2", "Class3", "Class4"})


def _format_path(symbol: MixinSymbol) -> str:
    """Format a MixinSymbol's path as a dot-separated string."""
    return ".".join(str(segment) for segment in symbol.path)


def _collect_tree_ancestors(symbol: MixinSymbol) -> frozenset[MixinSymbol]:
    """Collect all ancestors of symbol following the .outer chain up to root."""
    ancestors: set[MixinSymbol] = set()
    current = symbol.outer
    while isinstance(current, MixinSymbol):
        ancestors.add(current)
        current = current.outer
    return frozenset(ancestors)


def _has_cyclic_inheritance(
    symbol: MixinSymbol, ancestors: frozenset[MixinSymbol]
) -> bool:
    """Check if any of symbol's qualified_this keys is an ancestor (structural cycle)."""
    for super_union in symbol.qualified_this:
        if super_union in ancestors:
            return True
    return False


def _symbol_tree_snapshot(
    symbol: MixinSymbol,
    _ancestors: frozenset[MixinSymbol] | None = None,
) -> dict[str, Any]:
    """Build a snapshot dict of the symbol subtree.

    For each node, captures:
    - other_overlays: list of paths of qualified_this keys (excluding self)
    - children: recursive dict of child symbols (only for scope symbols)

    Detects cycles via _ancestors to avoid infinite recursion on
    self-referential symbols (e.g. Container with DeBruijnIndex0: [Container, ~]).
    Ancestors include both tree-walk ancestors and symbol-tree ancestors
    (via .outer chain) to catch back-references to distant parent scopes.
    """
    if _ancestors is None:
        _ancestors = _collect_tree_ancestors(symbol)

    other_overlays = tuple(
        sorted(_format_path(super_symbol) for super_symbol in symbol.qualified_this if super_symbol is not symbol)
    )

    children: dict[str, Any] = {}
    if symbol.is_scope:
        child_ancestors = _ancestors | {symbol}
        seen_keys: set[Hashable] = set()
        for key in symbol:
            if key in seen_keys:
                continue
            seen_keys.add(key)
            child = symbol[key]
            if _has_cyclic_inheritance(child, child_ancestors):
                children[str(key)] = {"other_overlays": "<cycle>"}
                continue
            children[str(key)] = _symbol_tree_snapshot(child, child_ancestors)

    result: dict[str, Any] = {"other_overlays": other_overlays}
    if children:
        result["children"] = children
    return result


def _collect_all_super_symbols(symbol: MixinSymbol) -> set[MixinSymbol]:
    """Collect all MixinSymbols in the inheritance chain (including self) via qualified_this."""
    return set(symbol.qualified_this)


@pytest.fixture
def multi_module_scope() -> Scope:
    """Load and evaluate the multi-module composition fixture."""
    fixtures_definition = DirectoryMixinDefinition(
        bases=(), is_public=True, underlying=FIXTURES_PATH
    )
    root = evaluate(fixtures_definition, modules_public=True)
    result = root.MultiModuleComposition
    assert isinstance(result, Scope)
    return result


class TestMultiModuleCompositionFlat:
    """Test that Module3Flat.Class4's qualified_this contains all Class union symbols.

    Module2Flat defines: Class4
    Module3Flat inherits: [Module1], [Module2Flat]

    qualified_this transitively includes all Class symbols from all modules
    in the composition chain (Module1, Module2Flat, Module3Flat).
    """

    def test_class4_super_chain_contains_all_classes(
        self, multi_module_scope: Scope, snapshot: SnapshotAssertion
    ) -> None:
        module3 = multi_module_scope.Module3Flat
        assert isinstance(module3, Scope)

        class4_symbol = module3.symbol["Class4"]
        all_symbols = _collect_all_super_symbols(class4_symbol)

        non_synthetic = {symbol for symbol in all_symbols if symbol.key in CLASS_NAMES}
        non_synthetic_paths = sorted(
            ".".join(str(segment) for segment in symbol.path)
            for symbol in non_synthetic
        )

        assert non_synthetic_paths == snapshot(name="flat_class4_super_chain")


class TestMultiModuleCompositionSnapshot:
    """Snapshot tests capturing the full symbol tree of Module3 and Module3Flat."""

    def test_module3_symbol_tree(self, multi_module_scope: Scope, snapshot) -> None:
        module3 = multi_module_scope.Module3
        assert isinstance(module3, Scope)
        tree = _symbol_tree_snapshot(module3.symbol)
        assert tree == snapshot

    def test_module3_flat_symbol_tree(
        self, multi_module_scope: Scope, snapshot
    ) -> None:
        module3_flat = multi_module_scope.Module3Flat
        assert isinstance(module3_flat, Scope)
        tree = _symbol_tree_snapshot(module3_flat.symbol)
        assert tree == snapshot


class TestMultiModuleCompositionNested:
    """Test that Module3.Nested2.Class4's qualified_this contains all Class union symbols.

    Module2 defines: Nested2.Class4
    Module3 inherits: [Module1], [Module2]

    qualified_this transitively includes all Class symbols from all modules
    in the composition chain (Module1, Module2, Module3).
    """

    def test_class4_super_chain_contains_all_classes(
        self, multi_module_scope: Scope, snapshot: SnapshotAssertion
    ) -> None:
        module3 = multi_module_scope.Module3
        assert isinstance(module3, Scope)

        nested2 = module3.Nested2
        assert isinstance(nested2, Scope)

        class4_symbol = nested2.symbol["Class4"]
        all_symbols = _collect_all_super_symbols(class4_symbol)

        non_synthetic = {symbol for symbol in all_symbols if symbol.key in CLASS_NAMES}
        non_synthetic_paths = sorted(
            ".".join(str(segment) for segment in symbol.path)
            for symbol in non_synthetic
        )

        assert non_synthetic_paths == snapshot(name="nested_class4_super_chain")


class TestMultiModuleCompositionDiamond:
    """Test Module3Diamond with composition that reduces nesting depth.

    Module2Diamond.Nested2.Class4 extends [Class2] and [Nested3, ExtraNested, Class5].
    Module3Diamond = [Module1] + [Module2Diamond]

    The path [Nested3, ExtraNested, Class5] crosses multiple nesting levels,
    and Class5 itself extends [Class2] with de_bruijn=2. When composed into
    Module3Diamond, the composition-site depth differs from the origin depth.
    """

    def test_module3_diamond_symbol_tree(
        self, multi_module_scope: Scope, snapshot: SnapshotAssertion
    ) -> None:
        module3_diamond = multi_module_scope.Module3Diamond
        assert isinstance(module3_diamond, Scope)
        tree = _symbol_tree_snapshot(module3_diamond.symbol)
        assert tree == snapshot(name="module3_diamond_symbol_tree")


class TestMyRootFlatten:
    """Test MyRoot with flattening composition that compresses nesting levels.

    MyRoot:
      Target: []
      Target2: []
      Nested1:
        - [Nested2]
        - [Nested4]
      Nested2:
        Nested3:
          ReferenceToTarget: [Target]   # de_bruijn=2
      Nested4:
        Nested3:
          ReferenceToTarget: [Target2]  # de_bruijn=2
      Flatten: [Nested1, Nested3]

    For [MyRoot, Flatten, ReferenceToTarget] from [Nested2] path (de_bruijn=2):
      step 0: current=[MyRoot, Flatten], current_lexical=[MyRoot, Nested1, Nested3]
      step 1: current=[MyRoot, Nested1], current_lexical=[MyRoot, Nested2]
      step 2: current=[MyRoot], current_lexical=[MyRoot]
      Result: MyRoot["Target"] = [MyRoot, Target]

    For [MyRoot, Flatten, ReferenceToTarget] from [Nested4] path (de_bruijn=2):
      step 0: current=[MyRoot, Flatten], current_lexical=[MyRoot, Nested1, Nested3]
      step 1: current=[MyRoot, Nested1], current_lexical=[MyRoot, Nested4]
      step 2: current=[MyRoot], current_lexical=[MyRoot]
      Result: MyRoot["Target2"] = [MyRoot, Target2]
    """

    def test_my_root_symbol_tree(
        self, multi_module_scope: Scope, snapshot: SnapshotAssertion
    ) -> None:
        my_root = multi_module_scope.MyRoot
        assert isinstance(my_root, Scope)
        tree = _symbol_tree_snapshot(my_root.symbol)
        assert tree == snapshot(name="my_root_symbol_tree")

    def test_reroot_symbol_tree(
        self, multi_module_scope: Scope, snapshot: SnapshotAssertion
    ) -> None:
        reroot = multi_module_scope.Reroot
        assert isinstance(reroot, Scope)
        tree = _symbol_tree_snapshot(reroot.symbol)
        assert tree == snapshot(name="reroot_symbol_tree")

    def test_flatten_reference_to_target_outer_and_supers(
        self, multi_module_scope: Scope
    ) -> None:
        """Verify that outer and qualified_this are correctly set for the flatten case."""
        my_root = multi_module_scope.MyRoot
        assert isinstance(my_root, Scope)
        my_root_symbol = my_root.symbol

        flatten_symbol = my_root_symbol["Flatten"]
        reference_to_target_symbol = flatten_symbol["ReferenceToTarget"]

        # [MyRoot, Flatten, ReferenceToTarget].outer = [MyRoot, Flatten]
        assert reference_to_target_symbol.outer is flatten_symbol

        # The definition-site symbols that provide ReferenceToTarget through
        # different super paths should be strict supers of Flatten
        nested2_symbol = my_root_symbol["Nested2"]
        nested4_symbol = my_root_symbol["Nested4"]

        nested2_nested3_symbol = nested2_symbol["Nested3"]
        nested4_nested3_symbol = nested4_symbol["Nested3"]

        # Flatten inherits from [Nested1, Nested3]
        # Nested1 inherits from [Nested2] and [Nested4]
        # So Nested1.Nested3 merges Nested2.Nested3 and Nested4.Nested3
        # Both should be in qualified_this of Flatten (the composition-site parent)
        assert nested2_nested3_symbol in flatten_symbol.qualified_this
        assert nested4_nested3_symbol in flatten_symbol.qualified_this


class TestMergedValueOverride:
    """Test Merged with overridden Value definitions from different paths.

    MergedRoot:
      Foo:
        Value: []
        Bar: [Value]         # de_bruijn=1, origin_symbol=Foo
      Nested:
        Baz:
          - [Foo]
          - Value2: []
          - Value: [Value2]  # Baz overrides Value to depend on Value2
      Qux:
        - [Foo]
        - Value3: []
        - Value: [Value3]    # Qux overrides Value to depend on Value3
      Merged:
        - [Foo]
        - [Nested, Baz]
        - [Qux]

    Key question: When Merged.Bar resolves [Value] (de_bruijn=1),
    does the outer chain correctly navigate to the right Value?
    """

    def test_merged_root_symbol_tree(
        self, multi_module_scope: Scope, snapshot: SnapshotAssertion
    ) -> None:
        merged_root = multi_module_scope.MergedRoot
        assert isinstance(merged_root, Scope)
        tree = _symbol_tree_snapshot(merged_root.symbol)
        assert tree == snapshot(name="merged_root_symbol_tree")


class TestCompositionOuterChain:
    """Test that outer and qualified_this correctly map at each composition level.

    LexicalOuterConflict:
      GrandParent:
        Parent:
          Target: []
          Child:
            Ref: [Target]      # de_bruijn=1, origin_symbol=GrandParent.Parent.Child
      WrapperB:
        - [GrandParent]
        - Parent:
            Target2: []
            Target: [Target2]  # WrapperB overrides Target
      WrapperC:
        - [GrandParent]
        - Parent:
            Target3: []
            Target: [Target3]  # WrapperC overrides Target
      Merged:
        - [WrapperB]
        - [WrapperC]

    The outer chain at each level should reflect the composition-site structure:
      - Ref.outer is Merged.Parent.Child
      - Merged.Parent.Child.outer is Merged.Parent
      - Merged.Parent.outer is Merged

    And the definition-site symbols should appear in qualified_this:
      - GrandParent.Parent.Child in Merged.Parent.Child.qualified_this
      - GrandParent.Parent in Merged.Parent.qualified_this
      - GrandParent in Merged.qualified_this
    """

    def test_outer_chain_maps_correctly(self, multi_module_scope: Scope) -> None:
        """Verify outer at each level is the correct composition-site parent."""
        conflict_root = multi_module_scope.LexicalOuterConflict
        assert isinstance(conflict_root, Scope)
        conflict_root_symbol = conflict_root.symbol

        grandparent_symbol = conflict_root_symbol["GrandParent"]
        grandparent_parent_symbol = grandparent_symbol["Parent"]
        grandparent_parent_child_symbol = grandparent_parent_symbol["Child"]

        merged_symbol = conflict_root_symbol["Merged"]
        merged_parent_symbol = merged_symbol["Parent"]
        merged_parent_child_symbol = merged_parent_symbol["Child"]
        ref_symbol = merged_parent_child_symbol["Ref"]

        # Level 1: Ref.outer is Merged.Parent.Child (structural parent)
        assert ref_symbol.outer is merged_parent_child_symbol
        assert (
            grandparent_parent_child_symbol in merged_parent_child_symbol.qualified_this
        )

        # Level 2: Merged.Parent.Child.outer is Merged.Parent
        assert merged_parent_child_symbol.outer is merged_parent_symbol
        assert grandparent_parent_symbol in merged_parent_symbol.qualified_this

        # Level 3: Merged.Parent.outer is Merged
        assert merged_parent_symbol.outer is merged_symbol
        assert grandparent_symbol in merged_symbol.qualified_this



class TestFlattenedContainer:
    """Test that Library.Wrapper.IndirectFlatten flattens Types.Container via AltTypes."""

    def test_types_symbol_tree(
        self, multi_module_scope: Scope, snapshot: SnapshotAssertion
    ) -> None:
        library_symbol = multi_module_scope.symbol["Library"]
        types = library_symbol["Types"]
        assert snapshot(name="types_symbol_tree") == _symbol_tree_snapshot(types)

    def test_indirect_flatten_symbol_tree(
        self, multi_module_scope: Scope, snapshot: SnapshotAssertion
    ) -> None:
        library_symbol = multi_module_scope.symbol["Library"]
        wrapper = library_symbol["Wrapper"]
        indirect_flatten = wrapper["IndirectFlatten"]
        assert snapshot(name="indirect_flatten_symbol_tree") == _symbol_tree_snapshot(
            indirect_flatten
        )


class TestDeBruijnCompositionNavigation:
    """Test that de Bruijn references resolve correctly after composition flattening.

    Library:
      Types:
        Value: []
        Container:
          Content: [Value]
          DeBruijnIndex0: [Container, ~]    # de_bruijn=0
          DeBruijnIndex1: [Types, ~]      # de_bruijn=1
          DeBruijnIndex2: [Library, ~]      # de_bruijn=2
          DeBruijnIndex3: [MultiModuleComposition, ~]  # de_bruijn=3
      DirectFlatten:
        - [Types, Container]
        - DirectOnly: []
      Wrapper:
        AltTypes: [Types]
        IndirectFlatten:
          - [AltTypes, Container]
          - IndirectOnly: []
    Composed:
      - [Library, DirectFlatten]
      - [Library, Wrapper, IndirectFlatten]

    Composed flattens 3 levels (Library.Types.Container) into 1 level via two paths.
    Each reference uses a qualified-this reference [ScopeName, ~]
    which resolves to the scope itself at de_bruijn=N.

    De Bruijn navigation uses qualified_this to trace from composition-site back
    to definition-site. Expected resolution at each level:
      de_bruijn=0 → {Composed}
      de_bruijn=1 → {Wrapper.AltTypes, Wrapper2.AltTypes2}  (2 indirect paths)
      de_bruijn=2 → {Library}
      de_bruijn=3 → {MultiModuleComposition}
    """

    def test_de_bruijn_references_resolve_after_flattening(
        self, multi_module_scope: Scope, snapshot: SnapshotAssertion
    ) -> None:
        composed_symbol = multi_module_scope.symbol["Composed"]
        library_symbol = multi_module_scope.symbol["Library"]
        container_symbol = library_symbol["Types"]["Container"]

        # Each DeBruijnIndex symbol's qualified_this transitively includes
        # all union symbols from the composition chain.
        for index in range(4):
            reference_symbol = composed_symbol[f"DeBruijnIndex{index}"]
            super_union_paths = sorted(
                ".".join(str(segment) for segment in super_symbol.path)
                for super_symbol in reference_symbol.qualified_this
            )
            assert super_union_paths == snapshot(
                name=f"de_bruijn_index_{index}_super_unions"
            )

        # Verify de Bruijn resolution at each level via qualified_this navigation.
        # This traces the same path the runtime uses when resolving references.
        #
        # De Bruijn navigation uses qualified_this[definition_site] at each level:
        #   Level 0: definition_site = Container
        #            composed.qualified_this[Container] → {AltTypes, AltTypes2}
        #   Level 1: definition_site = Types
        #            AltTypes.qualified_this[Types] → {Library}
        #   Level 2: definition_site = Library
        #            Library.qualified_this[Library] → {MultiModuleComposition}

        types_symbol = library_symbol["Types"]

        # DeBruijnIndex0 (de_bruijn=0): resolves to Composed (self level)
        assert composed_symbol.path == ("MultiModuleComposition", "Composed")

        # DeBruijnIndex1 (de_bruijn=1): navigate 1 level up
        # composed.qualified_this[Container] gives AltTypes and AltTypes2
        resolved_1 = composed_symbol.qualified_this[container_symbol]
        resolved_1_paths = {symbol.path for symbol in resolved_1}
        assert ("MultiModuleComposition", "Library", "Wrapper", "AltTypes") in resolved_1_paths, (
            f"DeBruijnIndex1: expected Wrapper.AltTypes in resolved paths, got {resolved_1_paths}"
        )
        assert ("MultiModuleComposition", "Library", "Wrapper2", "AltTypes2") in resolved_1_paths, (
            f"DeBruijnIndex1: expected Wrapper2.AltTypes2 in resolved paths, got {resolved_1_paths}"
        )

        # DeBruijnIndex2 (de_bruijn=2): navigate 2 levels up
        # Level 0: Container → {AltTypes, AltTypes2}
        # Level 1: Types → {Library}
        resolved_2: frozenset[MixinSymbol] = frozenset()
        for level_1_symbol in resolved_1:
            resolved_2 = resolved_2 | frozenset(
                level_1_symbol.qualified_this.get(types_symbol, set())
            )
        resolved_2_paths = {symbol.path for symbol in resolved_2}
        assert ("MultiModuleComposition", "Library") in resolved_2_paths, (
            f"DeBruijnIndex2: expected Library in resolved paths, got {resolved_2_paths}"
        )

        # DeBruijnIndex3 (de_bruijn=3): navigate 3 levels up
        # Level 0: Container → {AltTypes, AltTypes2}
        # Level 1: Types → {Library}
        # Level 2: Library → {MultiModuleComposition}
        resolved_3: frozenset[MixinSymbol] = frozenset()
        for level_2_symbol in resolved_2:
            resolved_3 = resolved_3 | frozenset(
                level_2_symbol.qualified_this.get(library_symbol, set())
            )
        resolved_3_paths = {symbol.path for symbol in resolved_3}
        assert ("MultiModuleComposition",) in resolved_3_paths, (
            f"DeBruijnIndex3: expected MultiModuleComposition in resolved paths, got {resolved_3_paths}"
        )

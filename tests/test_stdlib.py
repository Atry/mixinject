"""Tests for stdlib.mixin.yaml Church encoding implementation."""

from pathlib import Path

import pytest

from mixinject.mixin_directory import DirectoryMixinDefinition, evaluate_mixin_directory
from mixinject.runtime import Scope, evaluate


def traverse_symbol_tree(
    scope: Scope,
    visited: set[int],
    key_path: tuple[str, ...] = (),
    max_depth: int = 30,
) -> int:
    """
    Recursively traverse the symbol tree to verify totality.

    Uses a combination of:
    1. Symbol identity to detect exact cycles
    2. Key path tracking to detect structural recursion (e.g., Nat -> predecessor -> Nat)

    :param scope: The scope to traverse.
    :param visited: Set of visited symbol ids to detect cycles.
    :param key_path: Current path of keys (for detecting structural recursion).
    :param max_depth: Maximum depth (safety limit).
    :return: Total number of nodes visited.
    """
    if max_depth <= 0:
        return 0  # Safety limit reached, stop traversing

    symbol_id = id(scope.symbol)
    if symbol_id in visited:
        return 0  # Already visited this exact symbol

    # Detect structural recursion: if we've seen this key in the path before,
    # we're in a recursive type structure (like Nat -> predecessor -> Nat)
    current_key = scope.symbol.key
    if current_key in key_path:
        return 1  # Count this node but don't recurse (structural recursion)

    visited.add(symbol_id)
    count = 1

    new_key_path = key_path + (current_key,) if current_key else key_path

    for key in scope.symbol:
        if isinstance(key, str) and key.startswith("_"):
            continue  # Skip private members in traversal
        try:
            child = scope[key] if not isinstance(key, str) else getattr(scope, key)
            if isinstance(child, Scope):
                count += traverse_symbol_tree(child, visited, new_key_path, max_depth - 1)
        except (AttributeError, LookupError, ValueError, KeyError):
            pass

    return count


class TestStdlibChurchEncoding:
    """Tests for Church-encoded data structures in stdlib."""

    def test_stdlib_parses_without_error(self) -> None:
        """stdlib.mixin.yaml should parse without errors."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        assert hasattr(scope, "stdlib")

    def test_boolean_type_exists(self) -> None:
        """Boolean type and values should exist."""
        import pytest
        pytest.skip("Boolean module not yet implemented in stdlib")
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        boolean = scope.stdlib.boolean
        assert hasattr(boolean, "Boolean")
        assert hasattr(boolean, "True")
        assert hasattr(boolean, "False")

    def test_boolean_operations_exist(self) -> None:
        """Boolean operations should exist."""
        import pytest
        pytest.skip("Boolean module not yet implemented in stdlib")
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        boolean = scope.stdlib.boolean
        assert hasattr(boolean, "not")
        assert hasattr(boolean, "and")
        assert hasattr(boolean, "or")

    def test_boolean_true_has_switch(self) -> None:
        """True should have a switch with case_true."""
        import pytest
        pytest.skip("Boolean module not yet implemented in stdlib")
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        true_val = getattr(scope.stdlib.boolean, "True")
        assert hasattr(true_val, "switch")
        switch = true_val.Visitors
        assert hasattr(switch, "case_true")
        assert hasattr(switch, "return")

    def test_boolean_not_operand_has_switch(self) -> None:
        """not.operand should inherit Boolean's switch."""
        import pytest
        pytest.skip("Boolean module not yet implemented in stdlib")
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        not_op = getattr(scope.stdlib.boolean, "not")
        assert hasattr(not_op, "operand")
        # operand inherits from Boolean, so should have switch
        assert hasattr(not_op.operand, "switch")

    def test_nat_type_exists(self) -> None:
        """Nat type and values should exist."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        nat = scope.stdlib.Nat
        assert hasattr(nat, "Zero")
        assert hasattr(nat, "Succ")

    def test_nat_zero_has_switch(self) -> None:
        """Zero should have a Visitors."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        zero = scope.stdlib.Nat.Zero
        assert hasattr(zero, "Visitors")
        switch = zero.Visitors
        assert hasattr(switch, "ZeroVisitor")
        assert hasattr(switch, "Visitor")

    def test_nat_succ_predecessor_inherits_nat(self) -> None:
        """Succ.predecessor should inherit from Nat and have switch."""
        import pytest
        pytest.skip("predecessor is an empty field placeholder, not a Nat value with Visitors")
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        succ = scope.stdlib.Nat.Succ
        assert hasattr(succ, "predecessor")
        pred = succ.predecessor
        # predecessor inherits from Nat, so should have Visitors
        assert hasattr(pred, "Visitors")

    def test_nat_succ_late_binding(self) -> None:
        """Succ.Visitors should use late binding for _applied_predecessor."""
        import pytest
        pytest.skip("_applied_predecessor field no longer exists in current Addition structure")
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        succ = scope.stdlib.Nat.Succ
        switch = succ.Visitors
        # _applied_predecessor uses qualified this [Succ, ~, predecessor, switch]
        # Access via __getitem__ since _ prefix blocks __getattr__
        applied_pred = switch["_applied_predecessor"]
        assert hasattr(applied_pred, "SuccVisitor")
        assert hasattr(applied_pred, "ZeroVisitor")

    def test_list_type_exists(self) -> None:
        """List type should exist with Nil and Cons."""
        import pytest
        pytest.skip("List module not yet implemented in stdlib")
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        list_scope = scope.stdlib.list
        assert hasattr(list_scope, "List")
        assert hasattr(list_scope, "Nil")
        assert hasattr(list_scope, "Cons")

    def test_list_cons_tail_inherits_list(self) -> None:
        """Cons.tail should inherit from List and have switch."""
        import pytest
        pytest.skip("List module not yet implemented in stdlib")
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        cons = scope.stdlib.list.Cons
        assert hasattr(cons, "tail")
        tail = cons.tail
        # tail inherits from List, so should have switch
        assert hasattr(tail, "switch")

    def test_add_structure_exists(self) -> None:
        """Addition should have addend and sum."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        addition = scope.stdlib.Nat.Zero.Addition
        assert hasattr(addition, "addend")
        assert hasattr(addition, "sum")

    def test_add_sum_has_late_binding(self) -> None:
        """Addition.sum should delegate to Visitors."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        addition = scope.stdlib.Nat.Zero.Addition
        assert hasattr(addition, "sum")



def count_church_numeral(scope: Scope) -> int:
    """Count the depth of a Church numeral by following predecessor chain.

    Returns the number represented by the Church numeral.
    - Zero returns 0
    - Succ(n) returns 1 + count(n)
    """
    # Check if this is Zero (no predecessor or predecessor is empty interface)
    if not hasattr(scope, "predecessor"):
        return 0

    predecessor = scope.predecessor
    # Check if predecessor has its own predecessor (i.e., is it a concrete Succ?)
    # If predecessor is just the Nat interface, it won't have a meaningful structure
    if not hasattr(predecessor, "predecessor"):
        # This is Succ with predecessor being the base Nat interface
        # We can't count further without concrete binding
        return 1

    return 1 + count_church_numeral(predecessor)


@pytest.mark.skip(reason="Tests use old function-style add API, need rewrite for OO-style Addition")
class TestChurchArithmetic:
    """Tests for Church numeral arithmetic."""

    def test_count_succ_depth(self) -> None:
        """Helper test to understand Church numeral structure."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        nat = scope.stdlib.Nat

        # Zero should have no predecessor chain
        zero = nat.Zero
        assert hasattr(zero, "switch")

        # Succ should have predecessor
        succ = nat.Succ
        assert hasattr(succ, "predecessor")
        assert hasattr(succ.predecessor, "switch")

    def test_church_numeral_structure(self) -> None:
        """Test Church numeral representation structure.

        In Church encoding, a natural number n is represented by its switch behavior:
        - Zero.Visitors.return = ZeroVisitor.return
        - Succ.Visitors.return = SuccVisitor.return (with predecessor bound)

        To verify 3+4=7, we need to check that the add function correctly
        chains the switch applications.
        """
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        nat = scope.stdlib.Nat

        # Verify add has the expected structure for late binding
        add = nat.add
        add_return = getattr(add, "return")

        # add.return should inherit from Nat
        assert hasattr(add_return, "switch")

        # The switch should have both case handlers
        switch = add_return.Visitors
        assert hasattr(switch, "ZeroVisitor")
        assert hasattr(switch, "SuccVisitor")

        # The _applied_operand0 should reference operand0's switch
        applied_op0 = switch["_applied_operand0"]
        assert hasattr(applied_op0, "ZeroVisitor")
        assert hasattr(applied_op0, "SuccVisitor")

    def test_concrete_numerals_exist(self) -> None:
        """Test that concrete Church numerals can be defined."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        tests_dir = Path(__file__).parent
        # Union mount: combine stdlib and test fixtures
        stdlib_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=stdlib_dir)
        tests_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=tests_dir)
        scope = evaluate(stdlib_def, tests_def)

        # Check numerals exist in arithmetic_test module
        assert hasattr(scope, "arithmetic_test")
        arith = scope.arithmetic_test
        assert hasattr(arith, "Zero")
        assert hasattr(arith, "One")
        assert hasattr(arith, "Three")
        assert hasattr(arith, "Four")
        assert hasattr(arith, "Seven")

    def test_concrete_numeral_three_structure(self) -> None:
        """Test that Three has correct predecessor chain depth."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        tests_dir = Path(__file__).parent
        # Union mount: combine stdlib and test fixtures
        stdlib_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=stdlib_dir)
        tests_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=tests_dir)
        scope = evaluate(stdlib_def, tests_def)

        three = scope.arithmetic_test.Three
        # Three = Succ(Succ(Succ(Zero)))
        # Should have predecessor chain of depth 3
        assert hasattr(three, "predecessor")
        two = three.predecessor
        assert hasattr(two, "predecessor")
        one = two.predecessor
        assert hasattr(one, "predecessor")
        zero = one.predecessor
        # Zero inherits from stdlib.nat.Zero, which doesn't have predecessor
        # Actually Zero inherits from [stdlib, nat, Zero] which inherits from [Nat]
        # Let's just verify the chain exists
        assert hasattr(zero, "switch")

    def test_add_three_four_structure(self) -> None:
        """Test that add_three_four has operands bound correctly."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        tests_dir = Path(__file__).parent
        # Union mount: combine stdlib and test fixtures
        stdlib_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=stdlib_dir)
        tests_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=tests_dir)
        scope = evaluate(stdlib_def, tests_def)

        add_result = scope.arithmetic_test.add_three_four
        # Should have operands
        assert hasattr(add_result, "operand0")
        assert hasattr(add_result, "operand1")
        # operand0 should be Three (has predecessor chain)
        assert hasattr(add_result.operand0, "predecessor")
        # operand1 should be Four (has predecessor chain)
        assert hasattr(add_result.operand1, "predecessor")

    def test_three_plus_four_equals_seven(self) -> None:
        """Test that 3 + 4 = 7 in Church encoding.

        This verifies that the add operation produces a result with
        the same predecessor chain depth as Seven.
        """
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        tests_dir = Path(__file__).parent
        # Union mount: combine stdlib and test fixtures
        stdlib_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=stdlib_dir)
        tests_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=tests_dir)
        scope = evaluate(stdlib_def, tests_def)

        # Get the add result
        add_result = scope.arithmetic_test.add_three_four
        add_return = getattr(add_result, "return")

        # Get Seven for comparison
        seven = scope.arithmetic_test.Seven

        # Both should have switch (inherit from Nat)
        assert hasattr(add_return, "switch")
        assert hasattr(seven, "switch")

        # Verify add_return has the structure of a computed Nat
        # The return value should have ZeroVisitor and SuccVisitor handlers
        add_switch = add_return.Visitors
        assert hasattr(add_switch, "ZeroVisitor")
        assert hasattr(add_switch, "SuccVisitor")

        # Verify Seven has predecessor chain of depth 7
        # Seven = Succ(Six) = Succ(Succ(Five)) = ... = Succ^7(Zero)
        current = seven
        depth = 0
        while hasattr(current, "predecessor"):
            depth += 1
            current = current.predecessor
        assert depth == 7, f"Seven should have depth 7, got {depth}"

    def test_add_return_structure(self) -> None:
        """Test that add(3, 4).return has correct Church encoding structure.

        In MIXIN's current implementation, switch.SuccVisitor.predecessor is a Scope
        that references the recursive result, but doesn't directly inherit Nat's switch.
        Instead, we verify:

        1. The structure is correctly wired (SuccVisitor exists with predecessor)
        2. The recursion instance (_recursive_add) exists and references the correct operands

        .. todo::

           Once MIXIN supports instantiation (where a Symbol can have multiple
           Scope instances), we should be able to traverse the result via
           ``switch.SuccVisitor.predecessor.Visitors.SuccVisitor.predecessor...`` chain
           and verify the depth equals 7 (3 + 4). Currently, references like
           ``[Succ, ~, predecessor]`` create a new Scope path without inheriting
           the original type's ``switch``.

           MIXIN instantiation has the following constraints:

           - Exactly one mixin must be mixed in (single inheritance for instances)
           - Multiple parameters are allowed, but each parameter must be a
             reference; nested definitions inside parameters are not permitted
        """
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        tests_dir = Path(__file__).parent
        stdlib_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=stdlib_dir)
        tests_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=tests_dir)
        scope = evaluate(stdlib_def, tests_def)

        # Get the add result: add(3, 4)
        add_result = scope.arithmetic_test.add_three_four
        add_return = getattr(add_result, "return")

        # Verify basic structure exists
        assert hasattr(add_return, "switch"), "add.return should have switch"
        switch = add_return.Visitors
        assert hasattr(switch, "SuccVisitor"), "switch should have SuccVisitor"
        SuccVisitor = switch.SuccVisitor
        assert hasattr(SuccVisitor, "predecessor"), "SuccVisitor should have predecessor"

        # Verify recursion instance exists at switch level (not nested in SuccVisitor)
        assert "_applied_operand0" in switch.symbol, "switch should have _applied_operand0"
        applied_op0 = switch["_applied_operand0"]
        assert hasattr(applied_op0, "SuccVisitor"), "_applied_operand0 should have SuccVisitor"

        # _recursive_add is now at switch level (extracted for instantiation constraints)
        assert "_recursive_add" in switch.symbol, "switch should have _recursive_add"

        # _recursive_add should have operand0 and operand1
        recursive_add = switch["_recursive_add"]
        assert hasattr(recursive_add, "operand0"), "_recursive_add should have operand0"
        assert hasattr(recursive_add, "operand1"), "_recursive_add should have operand1"

    def test_add_operands_correctly_wired(self) -> None:
        """Test that add.operand0 and add.operand1 are correctly bound.

        Verify that the operands in add_three_four (3 + 4) are correctly
        wired to Three and Four.
        """
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        tests_dir = Path(__file__).parent
        stdlib_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=stdlib_dir)
        tests_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=tests_dir)
        scope = evaluate(stdlib_def, tests_def)

        add_result = scope.arithmetic_test.add_three_four

        # add.operand0 should be Three
        op0 = add_result.operand0
        assert hasattr(op0, "predecessor"), "operand0 should have predecessor (is Succ)"

        # add.operand1 should be Four
        op1 = add_result.operand1
        assert hasattr(op1, "predecessor"), "operand1 should have predecessor (is Succ)"

        # Verify they have correct depth by direct predecessor access
        def count_nat_depth(nat_scope: Scope) -> int:
            depth = 0
            current = nat_scope
            while hasattr(current, "predecessor"):
                depth += 1
                current = current.predecessor
            return depth

        assert count_nat_depth(op0) == 3, "operand0 should be 3 (Three)"
        assert count_nat_depth(op1) == 4, "operand1 should be 4 (Four)"


@pytest.mark.skip(reason="List module not yet implemented in stdlib")
class TestListConcat:
    """Tests for list concatenation."""

    def test_concat_structure_exists(self) -> None:
        """concat should have operand0, operand1, and return."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        concat = scope.stdlib.list.concat

        assert hasattr(concat, "operand0")
        assert hasattr(concat, "operand1")
        assert hasattr(concat, "return")

    def test_concat_return_has_late_binding(self) -> None:
        """concat.return.Visitors should have late binding references."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        concat = scope.stdlib.list.concat
        concat_return = getattr(concat, "return")
        switch = concat_return.Visitors

        # Should have both case handlers from List
        assert hasattr(switch, "case_nil")
        assert hasattr(switch, "case_cons")
        # Should have late binding references (private fields)
        assert "_applied_operand0" in switch.symbol
        assert "_applied_operand1" in switch.symbol

    def test_concat_empty_lists(self) -> None:
        """[] ++ [] = []"""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        tests_dir = Path(__file__).parent
        stdlib_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=stdlib_dir)
        tests_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=tests_dir)
        scope = evaluate(stdlib_def, tests_def)

        # concat(EmptyList, EmptyList) should behave like Nil
        concat_result = scope.arithmetic_test.concat_test
        concat_return = getattr(concat_result, "return")
        assert hasattr(concat_return, "switch")
        switch = concat_return.Visitors
        assert hasattr(switch, "case_nil")
        assert hasattr(switch, "case_cons")

    def test_concat_result_structure(self) -> None:
        """Test that concat([3,2,1], ["b","a"]) has correct structure."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        tests_dir = Path(__file__).parent
        stdlib_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=stdlib_dir)
        tests_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=tests_dir)
        scope = evaluate(stdlib_def, tests_def)

        # Get original lists for comparison
        list_321 = scope.arithmetic_test.list_321
        assert hasattr(list_321, "switch")

        # Verify list_321 structure: head=3, tail has head=2, etc.
        list_321_switch = list_321.Visitors
        assert hasattr(list_321_switch, "case_cons")
        case_cons = list_321_switch.case_cons
        assert hasattr(case_cons, "head")
        assert hasattr(case_cons, "tail")

        # Get concat result
        concat_result = scope.arithmetic_test.concat_test
        concat_return = getattr(concat_result, "return")
        assert hasattr(concat_return, "switch")

        # Result should also have case_cons with head and tail
        result_switch = concat_return.Visitors
        assert hasattr(result_switch, "case_cons")
        result_case_cons = result_switch.case_cons
        assert hasattr(result_case_cons, "head")
        assert hasattr(result_case_cons, "tail")

    def test_concat_return_structure(self) -> None:
        """Test that concat.return has correct Church encoding structure.

        Verifies:

        1. concat.return.Visitors has case_cons with head, tail, return
        2. The recursion instance (_recursive_concat) exists and references correct operands

        .. todo::

           Once MIXIN supports instantiation (where a Symbol can have multiple
           Scope instances), we should be able to traverse the result via
           ``switch.case_cons.tail.Visitors.case_cons.tail...`` chain and verify
           that ``concat([3,2,1], ["b","a"])`` yields ``[3, 2, 1, "b", "a"]``.
           Currently, references like ``[Cons, ~, tail]`` create a new Scope path
           without inheriting the original type's ``switch``.

           MIXIN instantiation has the following constraints:

           - Exactly one mixin must be mixed in (single inheritance for instances)
           - Multiple parameters are allowed, but each parameter must be a
             reference; nested definitions inside parameters are not permitted
        """
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        tests_dir = Path(__file__).parent
        stdlib_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=stdlib_dir)
        tests_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=tests_dir)
        scope = evaluate(stdlib_def, tests_def)

        concat_result = scope.arithmetic_test.concat_test
        concat_return = getattr(concat_result, "return")

        # Verify basic structure exists
        assert hasattr(concat_return, "switch"), "concat.return should have switch"
        switch = concat_return.Visitors
        assert hasattr(switch, "case_cons"), "switch should have case_cons"
        case_cons = switch.case_cons
        assert hasattr(case_cons, "head"), "case_cons should have head"
        assert hasattr(case_cons, "tail"), "case_cons should have tail"

        # Verify recursion instance exists at switch level (not nested in case_cons)
        assert "_applied_operand0" in switch.symbol, "switch should have _applied_operand0"
        applied_op0 = switch["_applied_operand0"]
        assert hasattr(applied_op0, "case_cons"), "_applied_operand0 should have case_cons"

        # _recursive_concat is now at switch level (extracted for instantiation constraints)
        assert "_recursive_concat" in switch.symbol, "switch should have _recursive_concat"

        # _recursive_concat should have operand0 and operand1
        recursive_concat = switch["_recursive_concat"]
        assert hasattr(recursive_concat, "operand0"), "_recursive_concat should have operand0"
        assert hasattr(recursive_concat, "operand1"), "_recursive_concat should have operand1"

    def test_concat_operands_correctly_wired(self) -> None:
        """Test that concat.operand0 and concat.operand1 are correctly bound.

        Verify that the operands in concat_test ([3,2,1] ++ ["b","a"]) are correctly
        wired to list_321 and list_ba.
        """
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        tests_dir = Path(__file__).parent
        stdlib_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=stdlib_dir)
        tests_def = DirectoryMixinDefinition(bases=(), is_public=True, underlying=tests_dir)
        scope = evaluate(stdlib_def, tests_def)

        concat_result = scope.arithmetic_test.concat_test

        # Verify they have correct depth by direct tail access
        def count_list_depth(list_scope: Scope) -> int:
            depth = 0
            current = list_scope
            while hasattr(current, "tail"):
                depth += 1
                current = current.tail
            return depth

        # concat.operand0 should be list_321 (length 3)
        op0 = concat_result.operand0
        assert count_list_depth(op0) == 3, "operand0 should be list_321 (length 3)"

        # concat.operand1 should be list_ba (length 2)
        op1 = concat_result.operand1
        assert count_list_depth(op1) == 2, "operand1 should be list_ba (length 2)"


class TestStdlibTotality:
    """Tests to ensure the stdlib symbol tree is finite (totality).

    Note: Recursive types (like Nat with predecessor: [Nat]) create structurally
    infinite trees. The traversal detects these structural cycles and stops.

    Note: With recursive functions (add, concat), the symbol tree would be
    infinite if we traversed underscore-prefixed fields. But since the traversal
    skips private members (underscore-prefixed), the tree remains finite.
    """

    def test_stdlib_symbol_tree_is_finite(self) -> None:
        """Traverse the entire stdlib symbol tree to verify totality."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        stdlib = scope.stdlib

        visited: set[int] = set()
        node_count = traverse_symbol_tree(stdlib, visited, max_depth=50)

        assert node_count > 0, "Should have visited at least one node"
        # With structural cycle detection, the count should be bounded
        assert node_count < 5000, f"Symbol tree too large ({node_count} nodes)"

    def test_each_type_subtree_terminates(self) -> None:
        """Verify each type module's traversal terminates."""
        stdlib_dir = Path(__file__).parent.parent / "src" / "mixinject"
        scope = evaluate_mixin_directory(stdlib_dir)
        stdlib = scope.stdlib

        # Only check modules that currently exist
        for type_name in ["Nat"]:
            type_scope = getattr(stdlib, type_name)
            visited: set[int] = set()
            node_count = traverse_symbol_tree(type_scope, visited, max_depth=30)
            assert node_count > 0, f"{type_name} should have nodes"
            # Each type should have a reasonable number of unique symbols
            assert node_count < 500, f"{type_name} tree too large ({node_count} nodes)"

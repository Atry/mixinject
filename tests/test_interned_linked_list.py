import gc

from mixinject import (
    DefinedScopeSymbol,
    ScopeSymbol,
    Scope,
    RootScopeSymbol,
    evaluate,
    resource,
    scope,
    StaticScope,
    _ScopeDefinition,
)


def _empty_definition() -> _ScopeDefinition:
    """Create a minimal empty scope definition for testing."""
    return _ScopeDefinition(scope_class=StaticScope, underlying=object())


class TestRoot:
    """Test root dependency graph behavior."""

    def test_root_hasintern_pool(self) -> None:
        scope_def = _empty_definition()
        root = RootScopeSymbol(definition=scope_def)
        assert root.intern_pool is not None

    def test_different_roots_have_different_pools(self) -> None:
        scope_def1 = _empty_definition()
        scope_def2 = _empty_definition()
        root1 = RootScopeSymbol(definition=scope_def1)
        root2 = RootScopeSymbol(definition=scope_def2)
        assert root1.intern_pool is not root2.intern_pool


class TestInterning:
    """Test interning behavior for O(1) equality.

    Note: Interning now happens in scope_factory and mount, not in __new__.
    Direct instantiation creates new objects each time.
    """

    def test_direct_instantiation_creates_new_objects(self) -> None:
        """Direct instantiation without going through scope_factory creates new objects."""
        scope_def = _empty_definition()
        nested_def = _empty_definition()
        root = RootScopeSymbol(definition=scope_def)
        child1 = DefinedScopeSymbol(outer=root, definition=nested_def, key="test1")
        child2 = DefinedScopeSymbol(outer=root, definition=nested_def, key="test2")
        # Without interning, these are different objects
        assert child1 is not child2

    def test_different_parent_different_object(self) -> None:
        scope_def = _empty_definition()
        nested_def = _empty_definition()
        root1 = RootScopeSymbol(definition=scope_def)
        root2 = RootScopeSymbol(definition=scope_def)
        child1 = DefinedScopeSymbol(outer=root1, definition=nested_def, key="test")
        child2 = DefinedScopeSymbol(outer=root2, definition=nested_def, key="test")
        assert child1 is not child2

    def test_each_node_has_ownintern_pool(self) -> None:
        scope_def = _empty_definition()
        nested_def = _empty_definition()
        root = RootScopeSymbol(definition=scope_def)
        child1 = DefinedScopeSymbol(outer=root, definition=nested_def, key="child1")
        child2 = DefinedScopeSymbol(outer=child1, definition=nested_def, key="child2")
        assert child1.intern_pool is not root.intern_pool
        assert child2.intern_pool is not child1.intern_pool
        assert child2.intern_pool is not root.intern_pool

    def test_interning_via_mount(self) -> None:
        """Interning happens when using mount."""
        @scope()
        class Root:
            @resource
            def foo() -> int:
                return 42

        root1 = evaluate(Root)
        root2 = evaluate(Root)

        # Different mount calls create different scopes
        assert root1 is not root2
        # But they should have different mixins since each mount creates a new root

    def test_interning_via_nested_scope_access(self) -> None:
        """Accessing the same nested scope multiple times returns scopes with the same mixin."""
        @scope()
        class Root:
            @scope()
            class Inner:
                @resource
                def foo() -> int:
                    return 42

        root = evaluate(Root)
        inner1 = root.Inner
        inner2 = root.Inner

        # Cached scope should return the same object
        assert inner1 is inner2
        # Therefore same mixin
        assert isinstance(inner1, Scope)
        assert isinstance(inner2, Scope)
        assert inner1.symbol is inner2.symbol


class TestWeakReference:
    """Test weak reference behavior of intern pool."""

    def test_intern_pool_supports_weak_references(self) -> None:
        """The intern pool is a WeakValueDictionary."""
        scope_def = _empty_definition()
        nested_def = _empty_definition()
        root = RootScopeSymbol(definition=scope_def)
        # Add an entry manually to the pool
        child = DefinedScopeSymbol(outer=root, definition=nested_def, key="test")
        root.intern_pool["test_key"] = child

        pool_size_before = len(root.intern_pool)
        assert pool_size_before == 1

        del child
        gc.collect()

        pool_size_after = len(root.intern_pool)
        assert pool_size_after < pool_size_before


class TestSubclass:
    """Test isinstance/issubclass behavior."""

    def test_root_is_subclass_of_symbol(self) -> None:
        assert issubclass(RootScopeSymbol, ScopeSymbol)

    def test_child_is_subclass_of_symbol(self) -> None:
        assert issubclass(DefinedScopeSymbol, ScopeSymbol)

    def test_root_instance_is_instance_of_symbol(self) -> None:
        scope_def = _empty_definition()
        root = RootScopeSymbol(definition=scope_def)
        assert isinstance(root, ScopeSymbol)

    def test_child_instance_is_instance_of_symbol(self) -> None:
        scope_def = _empty_definition()
        nested_def = _empty_definition()
        root = RootScopeSymbol(definition=scope_def)
        child = DefinedScopeSymbol(outer=root, definition=nested_def, key="test")
        assert isinstance(child, ScopeSymbol)

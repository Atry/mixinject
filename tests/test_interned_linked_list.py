import gc

from mixinject import (
    NestedMixin,
    Mixin,
    Proxy,
    RootMixin,
    evaluate,
    resource,
    scope,
    CachedProxy,
    _MixinDefinition,
    _NestedMixinSymbol,
    _RootSymbol,
    ChainMapSentinel,
)


def _empty_definition() -> _MixinDefinition:
    """Create a minimal empty proxy definition for testing."""
    return _MixinDefinition(proxy_class=CachedProxy, underlying=object())


def _empty_root_symbol(definition: _MixinDefinition) -> _RootSymbol:
    """Create a minimal root symbol for testing."""
    return _RootSymbol(definition=definition)


def _empty_nested_symbol(
    outer: "_RootSymbol", definition: _MixinDefinition
) -> _NestedMixinSymbol:
    """Create a minimal nested symbol for testing."""
    return _NestedMixinSymbol(
        outer=outer,
        name="__test__",
        definition=definition,
    )


class TestRoot:
    """Test root dependency graph behavior."""

    def test_root_hasintern_pool(self) -> None:
        proxy_def = _empty_definition()
        root_symbol = _empty_root_symbol(proxy_def)
        root = RootMixin(symbol=root_symbol)
        assert root.intern_pool is not None

    def test_different_roots_have_different_pools(self) -> None:
        proxy_def1 = _empty_definition()
        root_symbol1 = _empty_root_symbol(proxy_def1)
        proxy_def2 = _empty_definition()
        root_symbol2 = _empty_root_symbol(proxy_def2)
        root1 = RootMixin(symbol=root_symbol1)
        root2 = RootMixin(symbol=root_symbol2)
        assert root1.intern_pool is not root2.intern_pool


class TestInterning:
    """Test interning behavior for O(1) equality.

    Note: Interning now happens in proxy_factory and mount, not in __new__.
    Direct instantiation creates new objects each time.
    """

    def test_direct_instantiation_creates_new_objects(self) -> None:
        """Direct instantiation without going through proxy_factory creates new objects."""
        proxy_def = _empty_definition()
        root_symbol = _empty_root_symbol(proxy_def)
        nested_symbol = _empty_nested_symbol(root_symbol, proxy_def)
        root = RootMixin(symbol=root_symbol)
        child1 = NestedMixin(outer=root, symbol=nested_symbol, name="test1")
        child2 = NestedMixin(outer=root, symbol=nested_symbol, name="test2")
        # Without interning, these are different objects
        assert child1 is not child2

    def test_different_parent_different_object(self) -> None:
        proxy_def = _empty_definition()
        root_symbol = _empty_root_symbol(proxy_def)
        nested_symbol = _empty_nested_symbol(root_symbol, proxy_def)
        root1 = RootMixin(symbol=root_symbol)
        root2 = RootMixin(symbol=root_symbol)
        child1 = NestedMixin(outer=root1, symbol=nested_symbol, name="test")
        child2 = NestedMixin(outer=root2, symbol=nested_symbol, name="test")
        assert child1 is not child2

    def test_each_node_has_ownintern_pool(self) -> None:
        proxy_def = _empty_definition()
        root_symbol = _empty_root_symbol(proxy_def)
        nested_symbol = _empty_nested_symbol(root_symbol, proxy_def)
        root = RootMixin(symbol=root_symbol)
        child1 = NestedMixin(outer=root, symbol=nested_symbol, name="child1")
        child2 = NestedMixin(outer=child1, symbol=nested_symbol, name="child2")
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

        # Different mount calls create different proxies
        assert root1 is not root2
        # But they should have different mixins since each mount creates a new root

    def test_interning_via_nested_scope_access(self) -> None:
        """Accessing the same nested scope multiple times returns proxies with the same mixin."""
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

        # Cached proxy should return the same object
        assert inner1 is inner2
        # Therefore same mixin
        assert isinstance(inner1, Proxy)
        assert isinstance(inner2, Proxy)
        assert inner1.mixin is inner2.mixin


class TestWeakReference:
    """Test weak reference behavior of intern pool."""

    def test_intern_pool_supports_weak_references(self) -> None:
        """The intern pool is a WeakValueDictionary."""
        proxy_def = _empty_definition()
        root_symbol = _empty_root_symbol(proxy_def)
        nested_symbol = _empty_nested_symbol(root_symbol, proxy_def)
        root = RootMixin(symbol=root_symbol)
        # Add an entry manually to the pool
        child = NestedMixin(outer=root, symbol=nested_symbol, name="test")
        root.intern_pool["test_key"] = child

        pool_size_before = len(root.intern_pool)
        assert pool_size_before == 1

        del child
        gc.collect()

        pool_size_after = len(root.intern_pool)
        assert pool_size_after < pool_size_before


class TestSubclass:
    """Test isinstance/issubclass behavior."""

    def test_root_is_subclass_of_mixin(self) -> None:
        assert issubclass(RootMixin, Mixin)

    def test_child_is_subclass_of_mixin(self) -> None:
        assert issubclass(NestedMixin, Mixin)

    def test_root_instance_is_instance_of_mixin(self) -> None:
        proxy_def = _empty_definition()
        root_symbol = _empty_root_symbol(proxy_def)
        root = RootMixin(symbol=root_symbol)
        assert isinstance(root, Mixin)

    def test_child_instance_is_instance_of_mixin(self) -> None:
        proxy_def = _empty_definition()
        root_symbol = _empty_root_symbol(proxy_def)
        nested_symbol = _empty_nested_symbol(root_symbol, proxy_def)
        root = RootMixin(symbol=root_symbol)
        child = NestedMixin(outer=root, symbol=nested_symbol, name="test")
        assert isinstance(child, Mixin)

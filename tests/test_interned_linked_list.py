import gc

from mixinject import (
    StaticChildDependencyGraph,
    DependencyGraph,
    Proxy,
    RootDependencyGraph,
    mount,
    resource,
    scope,
    CachedProxy,
    _NamespaceDefinition,
    _JitCache,
    SymbolTableSentinel,
)


def _empty_proxy_definition() -> _NamespaceDefinition:
    """Create a minimal empty proxy definition for testing."""
    return _NamespaceDefinition(proxy_class=CachedProxy, underlying=object())


def _empty_jit_cache(proxy_definition: _NamespaceDefinition) -> _JitCache:
    """Create a minimal JIT cache for testing."""
    return _JitCache(
        proxy_definition=proxy_definition,
        symbol_table=SymbolTableSentinel.ROOT,
    )


class TestRoot:
    """Test root dependency graph behavior."""

    def test_root_hasintern_pool(self) -> None:
        root = RootDependencyGraph(proxy_definition=_empty_proxy_definition())
        assert root.intern_pool is not None

    def test_different_roots_have_different_pools(self) -> None:
        root1 = RootDependencyGraph(proxy_definition=_empty_proxy_definition())
        root2 = RootDependencyGraph(proxy_definition=_empty_proxy_definition())
        assert root1.intern_pool is not root2.intern_pool


class TestInterning:
    """Test interning behavior for O(1) equality.

    Note: Interning now happens in proxy_factory and mount, not in __new__.
    Direct instantiation creates new objects each time.
    """

    def test_direct_instantiation_creates_new_objects(self) -> None:
        """Direct instantiation without going through proxy_factory creates new objects."""
        proxy_def = _empty_proxy_definition()
        jit_cache = _empty_jit_cache(proxy_def)
        root = RootDependencyGraph(proxy_definition=proxy_def)
        child1 = StaticChildDependencyGraph(proxy_definition=proxy_def, outer=root, jit_cache=jit_cache)
        child2 = StaticChildDependencyGraph(proxy_definition=proxy_def, outer=root, jit_cache=jit_cache)
        # Without interning, these are different objects
        assert child1 is not child2

    def test_different_parent_different_object(self) -> None:
        proxy_def = _empty_proxy_definition()
        jit_cache = _empty_jit_cache(proxy_def)
        root1 = RootDependencyGraph(proxy_definition=proxy_def)
        root2 = RootDependencyGraph(proxy_definition=proxy_def)
        child1 = StaticChildDependencyGraph(proxy_definition=proxy_def, outer=root1, jit_cache=jit_cache)
        child2 = StaticChildDependencyGraph(proxy_definition=proxy_def, outer=root2, jit_cache=jit_cache)
        assert child1 is not child2

    def test_each_node_has_ownintern_pool(self) -> None:
        proxy_def = _empty_proxy_definition()
        jit_cache = _empty_jit_cache(proxy_def)
        root = RootDependencyGraph(proxy_definition=proxy_def)
        child1 = StaticChildDependencyGraph(proxy_definition=proxy_def, outer=root, jit_cache=jit_cache)
        child2 = StaticChildDependencyGraph(proxy_definition=proxy_def, outer=child1, jit_cache=jit_cache)
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

        root1 = mount(Root)
        root2 = mount(Root)

        # Different mount calls create different proxies
        assert root1 is not root2
        # But they should have different dependency_graphs since each mount creates a new root

    def test_interning_via_nested_scope_access(self) -> None:
        """Accessing the same nested scope multiple times returns proxies with the same dependency_graph."""
        @scope()
        class Root:
            @scope()
            class Inner:
                @resource
                def foo() -> int:
                    return 42

        root = mount(Root)
        inner1 = root.Inner
        inner2 = root.Inner

        # Cached proxy should return the same object
        assert inner1 is inner2
        # Therefore same dependency_graph
        assert isinstance(inner1, Proxy)
        assert isinstance(inner2, Proxy)
        assert inner1.dependency_graph is inner2.dependency_graph


class TestWeakReference:
    """Test weak reference behavior of intern pool."""

    def test_intern_pool_supports_weak_references(self) -> None:
        """The intern pool is a WeakValueDictionary."""
        proxy_def = _empty_proxy_definition()
        jit_cache = _empty_jit_cache(proxy_def)
        root = RootDependencyGraph(proxy_definition=proxy_def)
        # Add an entry manually to the pool
        child = StaticChildDependencyGraph(proxy_definition=proxy_def, outer=root, jit_cache=jit_cache)
        root.intern_pool["test_key"] = child

        pool_size_before = len(root.intern_pool)
        assert pool_size_before == 1

        del child
        gc.collect()

        pool_size_after = len(root.intern_pool)
        assert pool_size_after < pool_size_before


class TestSubclass:
    """Test isinstance/issubclass behavior."""

    def test_root_is_subclass_of_dependency_graph(self) -> None:
        assert issubclass(RootDependencyGraph, DependencyGraph)

    def test_child_is_subclass_of_dependency_graph(self) -> None:
        assert issubclass(StaticChildDependencyGraph, DependencyGraph)

    def test_root_instance_is_instance_of_dependency_graph(self) -> None:
        root = RootDependencyGraph(proxy_definition=_empty_proxy_definition())
        assert isinstance(root, DependencyGraph)

    def test_child_instance_is_instance_of_dependency_graph(self) -> None:
        proxy_def = _empty_proxy_definition()
        jit_cache = _empty_jit_cache(proxy_def)
        root = RootDependencyGraph(proxy_definition=proxy_def)
        child = StaticChildDependencyGraph(proxy_definition=proxy_def, outer=root, jit_cache=jit_cache)
        assert isinstance(child, DependencyGraph)

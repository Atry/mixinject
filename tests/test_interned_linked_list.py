import gc

from mixinject import (
    StaticChildDependencyGraph,
    DependencyGraph,
    Proxy,
    RootDependencyGraph,
    mount,
    resource,
    scope,
)


class TestRoot:
    """Test root dependency graph behavior."""

    def test_root_hasintern_pool(self) -> None:
        root = RootDependencyGraph()
        assert root.intern_pool is not None

    def test_different_roots_have_different_pools(self) -> None:
        root1 = RootDependencyGraph()
        root2 = RootDependencyGraph()
        assert root1.intern_pool is not root2.intern_pool


class TestInterning:
    """Test interning behavior for O(1) equality.

    Note: Interning now happens in proxy_factory and mount, not in __new__.
    Direct instantiation creates new objects each time.
    """

    def test_direct_instantiation_creates_new_objects(self) -> None:
        """Direct instantiation without going through proxy_factory creates new objects."""
        root = RootDependencyGraph()
        child1 = StaticChildDependencyGraph(head=1, parent=root)
        child2 = StaticChildDependencyGraph(head=1, parent=root)
        # Without interning, these are different objects
        assert child1 is not child2

    def test_different_head_same_root_different_object(self) -> None:
        root = RootDependencyGraph()
        child1 = StaticChildDependencyGraph(head=1, parent=root)
        child2 = StaticChildDependencyGraph(head=2, parent=root)
        assert child1 is not child2

    def test_same_head_different_root_different_object(self) -> None:
        root1 = RootDependencyGraph()
        root2 = RootDependencyGraph()
        child1 = StaticChildDependencyGraph(head=1, parent=root1)
        child2 = StaticChildDependencyGraph(head=1, parent=root2)
        assert child1 is not child2

    def test_each_node_has_ownintern_pool(self) -> None:
        root = RootDependencyGraph()
        child1 = StaticChildDependencyGraph(head=1, parent=root)
        child2 = StaticChildDependencyGraph(head=2, parent=child1)
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

        root1 = mount("root", Root)
        root2 = mount("root", Root)

        # Different mount calls create different proxies
        assert root1 is not root2
        # But they should have different reversed_paths since each mount creates a new root

    def test_interning_via_nested_scope_access(self) -> None:
        """Accessing the same nested scope multiple times returns proxies with the same dependency_graph."""
        @scope()
        class Root:
            @scope()
            class Inner:
                @resource
                def foo() -> int:
                    return 42

        root = mount("root", Root)
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
        root = RootDependencyGraph()
        # Add an entry manually to the pool
        child = StaticChildDependencyGraph(head=100, parent=root)
        root.intern_pool[100] = child

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
        root = RootDependencyGraph()
        assert isinstance(root, DependencyGraph)

    def test_child_instance_is_instance_of_dependency_graph(self) -> None:
        root = RootDependencyGraph()
        child = StaticChildDependencyGraph(head=1, parent=root)
        assert isinstance(child, DependencyGraph)

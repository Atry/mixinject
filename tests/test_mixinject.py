from typing import Callable, Iterator

from mixinject import (
    CachedProxy,
    Endo,
    Proxy,
    aggregator,
    patch,
    patches,
    resolve_root,
    resource,
    simple_component,
)


class TestSimpleResource:
    """Test basic resource definition and resolution."""

    def test_simple_resource_no_dependencies(self) -> None:
        class Namespace:
            greeting = resource(lambda: "Hello")

        root = resolve_root(Namespace)
        assert root.greeting == "Hello"

    def test_resource_with_dependency(self) -> None:
        class Namespace:
            name = resource(lambda: "World")
            greeting = resource(lambda name: f"Hello, {name}!")

        root = resolve_root(Namespace)
        assert root.greeting == "Hello, World!"

    def test_multiple_dependencies(self) -> None:
        class Namespace:
            first = resource(lambda: "First")
            second = resource(lambda: "Second")
            combined = resource(lambda first, second: f"{first} and {second}")

        root = resolve_root(Namespace)
        assert root.combined == "First and Second"


class TestPatch:
    """Test patch decorator."""

    def test_single_patch(self) -> None:
        class Base:
            value = resource(lambda: 10)

        class Patcher:
            value = patch(lambda: (lambda x: x * 2))

        root = resolve_root(Base, Patcher)
        assert root.value == 20

    def test_multiple_patches(self) -> None:
        class Base:
            value = resource(lambda: 10)

        class Patch1:
            value = patch(lambda: (lambda x: x + 5))

        class Patch2:
            value = patch(lambda: (lambda x: x + 3))

        root = resolve_root(Base, Patch1, Patch2)
        assert root.value == 18


class TestPatches:
    """Test patches decorator (multiple patches from single callable)."""

    def test_patches_decorator(self) -> None:
        class Base:
            value = resource(lambda: 10)

        class Patcher:
            value = patches(lambda: ((lambda x: x + 5), (lambda x: x + 3)))

        root = resolve_root(Base, Patcher)
        assert root.value == 18


class TestLexicalScope:
    """Test lexical scope lookup (same name parameter)."""

    def test_same_name_lookup_via_nested_scope(self) -> None:
        class Outer:
            counter = resource(lambda: 0)

            class Inner:
                counter = resource(lambda counter: counter + 1)

        root = resolve_root(Outer)
        assert root.counter == 0
        assert root.Inner.counter == 1


class TestSimpleComponent:
    """Test simple_component helper."""

    def test_simple_component_single_value(self) -> None:
        comp = simple_component(foo="bar")
        proxy = CachedProxy(components=frozenset((comp,)))
        assert proxy.foo == "bar"

    def test_simple_component_multiple_values(self) -> None:
        comp = simple_component(foo="bar", count=42, flag=True)
        proxy = CachedProxy(components=frozenset((comp,)))
        assert proxy.foo == "bar"
        assert proxy.count == 42
        assert proxy.flag is True


class TestAggregator:
    """Test aggregator decorator."""

    def test_custom_aggregation(self) -> None:
        class Base:
            tags = aggregator(lambda: frozenset)

        class Provider1:
            tags = patch(lambda: "tag1")

        class Provider2:
            tags = patch(lambda: "tag2")

        root = resolve_root(Base, Provider1, Provider2)
        assert root.tags == frozenset({"tag1", "tag2"})


class TestUnionMount:
    """Test union mount semantics with multiple objects."""

    def test_union_mount_multiple_namespaces(self) -> None:
        class Namespace1:
            foo = resource(lambda: "foo_value")

        class Namespace2:
            bar = resource(lambda: "bar_value")

        root = resolve_root(Namespace1, Namespace2)
        assert root.foo == "foo_value"
        assert root.bar == "bar_value"

    def test_union_mount_with_dependencies_across_namespaces(self) -> None:
        class Namespace1:
            base_value = resource(lambda: "base")

        class Namespace2:
            combined = resource(lambda base_value: f"{base_value}_combined")

        root = resolve_root(Namespace1, Namespace2)
        assert root.combined == "base_combined"


class TestProxyAsSymlink:
    """Test Proxy return values acting as symlinks."""

    def test_proxy_symlink(self) -> None:
        comp = simple_component(inner_value="inner")
        inner_proxy = CachedProxy(components=frozenset((comp,)))

        class Namespace:
            linked = resource(lambda: inner_proxy)

        root = resolve_root(Namespace)
        assert root.linked.inner_value == "inner"

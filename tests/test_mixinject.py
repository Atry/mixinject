import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterator

from mixinject import (
    CachedProxy,
    Endo,
    LazySubmoduleMapping,
    Proxy,
    aggregator,
    parse_module,
    patch,
    patches,
    resolve_root,
    resource,
    simple_component,
)

FIXTURES_DIR = str(Path(__file__).parent / "fixtures")


class TestSimpleResource:
    """Test basic resource definition and resolution."""

    def test_simple_resource_no_dependencies(self) -> None:
        class Namespace:
            @resource
            def greeting() -> str:
                return "Hello"

        root = resolve_root(Namespace)
        assert root.greeting == "Hello"

    def test_resource_with_dependency(self) -> None:
        class Namespace:
            @resource
            def name() -> str:
                return "World"

            @resource
            def greeting(name: str) -> str:
                return f"Hello, {name}!"

        root = resolve_root(Namespace)
        assert root.greeting == "Hello, World!"

    def test_multiple_dependencies(self) -> None:
        class Namespace:
            @resource
            def first() -> str:
                return "First"

            @resource
            def second() -> str:
                return "Second"

            @resource
            def combined(first: str, second: str) -> str:
                return f"{first} and {second}"

        root = resolve_root(Namespace)
        assert root.combined == "First and Second"


class TestPatch:
    """Test patch decorator."""

    def test_single_patch(self) -> None:
        class Base:
            @resource
            def value() -> int:
                return 10

        class Patcher:
            @patch
            def value() -> Callable[[int], int]:
                return lambda x: x * 2

        root = resolve_root(Base, Patcher)
        assert root.value == 20

    def test_multiple_patches(self) -> None:
        class Base:
            @resource
            def value() -> int:
                return 10

        class Patch1:
            @patch
            def value() -> Callable[[int], int]:
                return lambda x: x + 5

        class Patch2:
            @patch
            def value() -> Callable[[int], int]:
                return lambda x: x + 3

        root = resolve_root(Base, Patch1, Patch2)
        assert root.value == 18


class TestPatches:
    """Test patches decorator (multiple patches from single callable)."""

    def test_patches_decorator(self) -> None:
        class Base:
            @resource
            def value() -> int:
                return 10

        class Patcher:
            @patches
            def value() -> tuple[Callable[[int], int], ...]:
                return ((lambda x: x + 5), (lambda x: x + 3))

        root = resolve_root(Base, Patcher)
        assert root.value == 18


class TestLexicalScope:
    """Test lexical scope lookup (same name parameter)."""

    def test_same_name_lookup_via_nested_scope(self) -> None:
        class Outer:
            @resource
            def counter() -> int:
                return 0

            class Inner:
                @resource
                def counter(counter: int) -> int:
                    return counter + 1

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
            @aggregator
            def tags() -> type[frozenset]:
                return frozenset

        class Provider1:
            @patch
            def tags() -> str:
                return "tag1"

        class Provider2:
            @patch
            def tags() -> str:
                return "tag2"

        root = resolve_root(Base, Provider1, Provider2)
        assert root.tags == frozenset({"tag1", "tag2"})


class TestUnionMount:
    """Test union mount semantics with multiple objects."""

    def test_union_mount_multiple_namespaces(self) -> None:
        class Namespace1:
            @resource
            def foo() -> str:
                return "foo_value"

        class Namespace2:
            @resource
            def bar() -> str:
                return "bar_value"

        root = resolve_root(Namespace1, Namespace2)
        assert root.foo == "foo_value"
        assert root.bar == "bar_value"

    def test_union_mount_with_dependencies_across_namespaces(self) -> None:
        class Namespace1:
            @resource
            def base_value() -> str:
                return "base"

        class Namespace2:
            @resource
            def combined(base_value: str) -> str:
                return f"{base_value}_combined"

        root = resolve_root(Namespace1, Namespace2)
        assert root.combined == "base_combined"

    def test_deduplicated_tags_from_docstring(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            from union_mount import branch0, branch1, branch2

            root = resolve_root(branch0, branch1, branch2)
            assert root.deduplicated_tags == frozenset({"tag1", "tag2_dependency_value"})
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("union_mount", None)
            sys.modules.pop("union_mount.branch0", None)
            sys.modules.pop("union_mount.branch1", None)
            sys.modules.pop("union_mount.branch2", None)

    def test_union_mount_point_from_docstring(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            from union_mount import branch0, branch1, branch2

            root = resolve_root(branch0, branch1, branch2)
            assert root.union_mount_point.foo == "foo"
            assert root.union_mount_point.bar == "foo_bar"
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("union_mount", None)
            sys.modules.pop("union_mount.branch0", None)
            sys.modules.pop("union_mount.branch1", None)
            sys.modules.pop("union_mount.branch2", None)


class TestProxyAsSymlink:
    """Test Proxy return values acting as symlinks."""

    def test_proxy_symlink(self) -> None:
        comp = simple_component(inner_value="inner")
        inner_proxy = CachedProxy(components=frozenset((comp,)))

        class Namespace:
            @resource
            def linked() -> Proxy:
                return inner_proxy

        root = resolve_root(Namespace)
        assert root.linked.inner_value == "inner"


class TestModuleParsing:
    """Test module and package parsing with pkgutil/importlib."""

    def test_parse_module_returns_lazy_mapping_for_package(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import regular_pkg

            scope_def = parse_module(regular_pkg)
            assert isinstance(scope_def, LazySubmoduleMapping)
            assert "child" in scope_def.submodule_names
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("regular_pkg", None)
            sys.modules.pop("regular_pkg.child", None)

    def test_lazy_submodule_import(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import regular_pkg

            scope_def = parse_module(regular_pkg)
            assert "regular_pkg.child" not in sys.modules
            _ = scope_def["child"]
            assert "regular_pkg.child" in sys.modules
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("regular_pkg", None)
            sys.modules.pop("regular_pkg.child", None)

    def test_resolve_root_with_package(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import regular_pkg

            root = resolve_root(regular_pkg)
            assert root.pkg_value == "from_pkg"
            assert root.child.child_value == "from_child"
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("regular_pkg", None)
            sys.modules.pop("regular_pkg.child", None)

    def test_parse_regular_module_returns_dict(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import regular_mod

            scope_def = parse_module(regular_mod)
            assert isinstance(scope_def, dict)
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("regular_mod", None)

    def test_namespace_package_discovery(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import ns_pkg

            assert hasattr(ns_pkg, "__path__")
            scope_def = parse_module(ns_pkg)
            assert isinstance(scope_def, LazySubmoduleMapping)
            assert "mod_a" in scope_def.submodule_names
            assert "mod_b" in scope_def.submodule_names

            root = resolve_root(ns_pkg)
            assert root.mod_a.value_a == "a"
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("ns_pkg", None)
            sys.modules.pop("ns_pkg.mod_a", None)
            sys.modules.pop("ns_pkg.mod_b", None)

    def test_namespace_package_submodule_with_internal_dependency(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import ns_pkg

            root = resolve_root(ns_pkg)
            assert root.mod_b.base == "base"
            assert root.mod_b.derived == "base_derived"
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("ns_pkg", None)
            sys.modules.pop("ns_pkg.mod_a", None)
            sys.modules.pop("ns_pkg.mod_b", None)

    def test_namespace_package_union_mount_multiple_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ns_pkg_dir = Path(tmpdir) / "ns_pkg"
            ns_pkg_dir.mkdir()
            (ns_pkg_dir / "mod_c.py").write_text(
                "from mixinject import resource\n"
                "value_c = resource(lambda: 'c')\n"
            )

            sys.path.insert(0, FIXTURES_DIR)
            sys.path.insert(0, tmpdir)
            try:
                import ns_pkg

                assert len(ns_pkg.__path__) == 2
                scope_def = parse_module(ns_pkg)
                assert isinstance(scope_def, LazySubmoduleMapping)
                assert "mod_a" in scope_def.submodule_names
                assert "mod_b" in scope_def.submodule_names
                assert "mod_c" in scope_def.submodule_names

                root = resolve_root(ns_pkg)
                assert root.mod_a.value_a == "a"
                assert root.mod_c.value_c == "c"
            finally:
                sys.path.remove(FIXTURES_DIR)
                sys.path.remove(tmpdir)
                sys.modules.pop("ns_pkg", None)
                sys.modules.pop("ns_pkg.mod_a", None)
                sys.modules.pop("ns_pkg.mod_b", None)
                sys.modules.pop("ns_pkg.mod_c", None)

import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterator

from mixinject import (
    AggregatorDefinition,
    Builder,
    CachedProxy,
    KeywordArgumentMixin,
    PackageMapping,
    ObjectMapping,
    Proxy,
    ResourceDefinition,
    SinglePatchDefinition,
    aggregator,
    BoundMixin,
    parameter,
    patch,
    patches,
    resource,
    resolve,
    resolve,
    scope,
    parse_module,
    WeakCachedScope,
)

FIXTURES_DIR = str(Path(__file__).parent / "fixtures")


class TestSimpleResource:
    """Test basic resource definition and resolution."""

    def test_simple_resource_no_dependencies(self) -> None:
        class Namespace:
            @resource
            def greeting() -> str:
                return "Hello"

        root = resolve(Namespace)
        assert root.greeting == "Hello"

    def test_resource_with_dependency(self) -> None:
        class Namespace:
            @resource
            def name() -> str:
                return "World"

            @resource
            def greeting(name: str) -> str:
                return f"Hello, {name}!"

        root = resolve(Namespace)
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

        root = resolve(Namespace)
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

        root = resolve(Base, Patcher)
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

        root = resolve(Base, Patch1, Patch2)
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

        root = resolve(Base, Patcher)
        assert root.value == 18


class TestLexicalScope:
    """Test lexical scope lookup (same name parameter)."""

    def test_same_name_lookup_via_nested_scope(self) -> None:
        class Outer:
            @resource
            def counter() -> int:
                return 0

            @scope
            class Inner:
                @resource
                def counter(counter: int) -> int:
                    return counter + 1

        root = resolve(Outer)
        assert root.counter == 0
        assert root.Inner.counter == 1


class TestKeywordArgumentMixin:
    """Test KeywordArgumentMixin."""

    def test_keyword_argument_mixin_single_value(self) -> None:
        comp = KeywordArgumentMixin(kwargs={"foo": "bar"})
        proxy = CachedProxy(mixins=frozenset((comp,)))
        assert proxy.foo == "bar"

    def test_keyword_argument_mixin_multiple_values(self) -> None:
        comp = KeywordArgumentMixin(kwargs={"foo": "bar", "count": 42, "flag": True})
        proxy = CachedProxy(mixins=frozenset((comp,)))
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

        root = resolve(Base, Provider1, Provider2)
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

        root = resolve(Namespace1, Namespace2)
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

        root = resolve(Namespace1, Namespace2)
        assert root.combined == "base_combined"

    def test_deduplicated_tags_from_docstring(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            from union_mount import branch0, branch1, branch2

            root = resolve(branch0, branch1, branch2)
            assert root.deduplicated_tags == frozenset(
                {"tag1", "tag2_dependency_value"}
            )
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

            root = resolve(branch0, branch1, branch2)
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
        comp = KeywordArgumentMixin(kwargs={"inner_value": "inner"})
        inner_proxy = CachedProxy(mixins=frozenset((comp,)))

        class Namespace:
            @resource
            def linked() -> Proxy:
                return inner_proxy

        root = resolve(Namespace)
        assert root.linked.inner_value == "inner"


class TestModuleParsing:
    """Test module and package parsing with pkgutil/importlib."""

    def test_parse_module_returns_lazy_mapping_for_package(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import regular_pkg

            scope_def = parse_module(regular_pkg, get_module_proxy_class=lambda _: CachedProxy)
            assert isinstance(scope_def, PackageMapping)
            assert "child" in scope_def
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("regular_pkg", None)
            sys.modules.pop("regular_pkg.child", None)

    def test_lazy_submodule_import(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import regular_pkg

            scope_def = parse_module(regular_pkg, get_module_proxy_class=lambda _: CachedProxy)
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

            root = resolve(regular_pkg)
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

            scope_def = parse_module(regular_mod, get_module_proxy_class=lambda _: CachedProxy)
            assert isinstance(scope_def, ObjectMapping)
            assert not isinstance(scope_def, PackageMapping)
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("regular_mod", None)

    def test_namespace_package_discovery(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import ns_pkg

            assert hasattr(ns_pkg, "__path__")
            scope_def = parse_module(ns_pkg, get_module_proxy_class=lambda _: CachedProxy)
            assert isinstance(scope_def, PackageMapping)
            assert "mod_a" in scope_def
            assert "mod_b" in scope_def

            root = resolve(ns_pkg)
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

            root = resolve(ns_pkg)
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
                "from mixinject import resource\n" "value_c = resource(lambda: 'c')\n"
            )

            sys.path.insert(0, FIXTURES_DIR)
            sys.path.insert(0, tmpdir)
            try:
                import ns_pkg

                assert len(ns_pkg.__path__) == 2
                scope_def = parse_module(ns_pkg, get_module_proxy_class=lambda _: CachedProxy)
                assert isinstance(scope_def, PackageMapping)
                assert "mod_a" in scope_def
                assert "mod_b" in scope_def
                assert "mod_c" in scope_def

                root = resolve(ns_pkg)
                assert root.mod_a.value_a == "a"
                assert root.mod_c.value_c == "c"
            finally:
                sys.path.remove(FIXTURES_DIR)
                sys.path.remove(tmpdir)
                sys.modules.pop("ns_pkg", None)
                sys.modules.pop("ns_pkg.mod_a", None)
                sys.modules.pop("ns_pkg.mod_b", None)
                sys.modules.pop("ns_pkg.mod_c", None)


class TestProxyCallable:
    """Test Proxy as Callable - dynamic mixin injection."""

    def test_proxy_call_single_kwarg(self) -> None:
        """Test calling Proxy to inject a single new value."""
        comp = KeywordArgumentMixin(kwargs={"foo": "foo_value"})
        proxy = CachedProxy(mixins=frozenset((comp,)))

        # Call proxy with new kwargs to add additional mixins
        new_proxy = proxy(bar="bar_value")

        assert new_proxy.foo == "foo_value"  # from original mixin
        assert new_proxy.bar == "bar_value"  # from new call

    def test_proxy_call_multiple_kwargs(self) -> None:
        """Test calling Proxy with multiple new kwargs."""
        comp = KeywordArgumentMixin(kwargs={"x": 1, "y": 2})
        proxy = CachedProxy(mixins=frozenset((comp,)))

        # Call to add new mixins (z and w)
        new_proxy = proxy(z=3, w=4)

        assert new_proxy.x == 1  # from original
        assert new_proxy.y == 2  # from original
        assert new_proxy.z == 3  # new
        assert new_proxy.w == 4  # new

    def test_proxy_call_injected_values_accessible(self) -> None:
        """Test that values injected via Proxy call are accessible as resources."""
        # Create empty proxy and inject values via call
        proxy = CachedProxy(mixins=frozenset([]))(config={"db": "postgres"})(timeout=30)

        # Injected values should be accessible
        assert proxy.config == {"db": "postgres"}
        assert proxy.timeout == 30

    def test_proxy_call_provides_endo_only_base_value(self) -> None:
        """Test Proxy callable providing base value for endo-only resource pattern.

        Pattern:
        - Outer scope provides base value via Proxy.__call__
        - Module has nested scope that depends on parameter with same name
        - Same-name lookup (param == resource name) finds value from outer scope
        """

        class Config:
            @resource
            def db_config(db_config: dict) -> dict:
                """Endo-only resource with same-name parameter

                Since param name == resource name, it looks up 'db_config'
                in outer lexical scope, getting the value from Proxy.__call__
                """
                return db_config

            @resource
            def connection_string(db_config: dict) -> str:
                """Depends on db_config which comes from outer scope"""
                return f"{db_config['host']}:{db_config['port']}"

        # Provide the base value via Proxy.__call__
        outer_proxy = CachedProxy(mixins=frozenset([]))(
            db_config={"host": "localhost", "port": "5432"}
        )

        def outer_scope() -> Iterator[Proxy]:
            yield outer_proxy

        root = resolve(Config, lexical_scope=outer_scope)
        assert root.db_config == {"host": "localhost", "port": "5432"}
        assert root.connection_string == "localhost:5432"

    def test_proxy_call_returns_same_type(self) -> None:
        """Test that calling a Proxy subclass returns the same type."""
        class Value:
            pass

        v1, v2 = Value(), Value()
        comp = KeywordArgumentMixin(kwargs={"x": v1})

        # CachedProxy should return CachedProxy
        cached = CachedProxy(mixins=frozenset((comp,)))
        new_cached = cached(y=v2)
        assert isinstance(new_cached, CachedProxy)
        assert new_cached.x is v1
        assert new_cached.y is v2

        # WeakCachedScope should return WeakCachedScope
        weak = WeakCachedScope(mixins=frozenset((comp,)))
        new_weak = weak(y=v2)
        assert isinstance(new_weak, WeakCachedScope)
        assert new_weak.x is v1
        assert new_weak.y is v2

    def test_proxy_call_creates_fresh_instance(self) -> None:
        """Test that calling a Proxy creates a new instance without modifying the original."""
        comp = KeywordArgumentMixin(kwargs={"a": 1})
        proxy1 = CachedProxy(mixins=frozenset((comp,)))

        # Call to create a new proxy
        proxy2 = proxy1(b=2)

        # Original should be unchanged
        assert proxy1.a == 1
        # New proxy should have both
        assert proxy2.a == 1
        assert proxy2.b == 2
        # They should be different instances
        assert proxy1 is not proxy2


class TestProxyDir:
    """Test Proxy.__dir__ method."""

    def test_dir_returns_list(self) -> None:
        """Test that __dir__ returns a list."""

        class Namespace:
            @resource
            def foo() -> str:
                return "foo"

        root = resolve(Namespace)
        result = dir(root)
        assert isinstance(result, list)

    def test_dir_includes_resource_names(self) -> None:
        """Test that __dir__ includes all resource names."""

        class Namespace:
            @resource
            def resource1() -> str:
                return "r1"

            @resource
            def resource2() -> str:
                return "r2"

            @resource
            def resource3() -> str:
                return "r3"

        root = resolve(Namespace)
        result = dir(root)
        assert "resource1" in result
        assert "resource2" in result
        assert "resource3" in result

    def test_dir_includes_builtin_attrs(self) -> None:
        """Test that __dir__ includes builtin attributes."""

        class Namespace:
            @resource
            def foo() -> str:
                return "foo"

        root = resolve(Namespace)
        result = dir(root)
        assert "__class__" in result
        assert "__getitem__" in result
        assert "mixins" in result

    def test_dir_is_sorted(self) -> None:
        """Test that __dir__ returns a sorted list."""

        class Namespace:
            @resource
            def zebra() -> str:
                return "z"

            @resource
            def apple() -> str:
                return "a"

            @resource
            def middle() -> str:
                return "m"

        root = resolve(Namespace)
        result = dir(root)
        assert result == sorted(result)

    def test_dir_with_multiple_mixins(self) -> None:
        """Test __dir__ with multiple mixins providing different resources."""

        class Namespace1:
            @resource
            def foo() -> str:
                return "foo"

        class Namespace2:
            @resource
            def bar() -> str:
                return "bar"

        root = resolve(Namespace1, Namespace2)
        result = dir(root)
        assert "foo" in result
        assert "bar" in result

    def test_dir_deduplicates_names(self) -> None:
        """Test that __dir__ deduplicates resource names when multiple mixins provide the same name."""

        class Namespace1:
            @resource
            def shared() -> str:
                return "from_ns1"

        class Namespace2:
            @patch
            def shared() -> Callable[[str], str]:
                return lambda s: s + "_patched"

        root = resolve(Namespace1, Namespace2)
        result = dir(root)
        assert result.count("shared") == 1

    def test_dir_works_with_cached_proxy(self) -> None:
        """Test __dir__ works with CachedProxy subclass."""

        class Namespace:
            @resource
            def cached_resource() -> str:
                return "cached"

        root = resolve(Namespace, root_proxy_class=CachedProxy)
        result = dir(root)
        assert "cached_resource" in result

    def test_dir_works_with_weak_cached_scope(self) -> None:
        """Test __dir__ works with WeakCachedScope subclass."""

        class Namespace:
            @resource
            def weak_resource() -> str:
                return "weak"

        root = resolve(Namespace, root_proxy_class=WeakCachedScope)
        result = dir(root)
        assert "weak_resource" in result

    def test_dir_accessible_via_getattr(self) -> None:
        """Test that all resource names from __dir__ are accessible via getattr."""

        class Namespace:
            @resource
            def accessible1() -> str:
                return "a1"

            @resource
            def accessible2() -> str:
                return "a2"

        root = resolve(Namespace)
        assert "accessible1" in dir(root)
        assert "accessible2" in dir(root)
        assert getattr(root, "accessible1") == "a1"
        assert getattr(root, "accessible2") == "a2"


class TestParameter:
    """Test parameter decorator as syntactic sugar for empty patches."""

    def test_parameter_with_keyword_argument_mixin(self) -> None:
        """Test that @parameter registers a resource name and accepts injected values."""

        class Config:
            @parameter
            def database_url(): ...

            @resource
            def connection_string(database_url: str) -> str:
                return f"Connected to: {database_url}"

        root = resolve(Config)(database_url="postgresql://localhost/mydb")
        assert root.connection_string == "Connected to: postgresql://localhost/mydb"

    def test_parameter_with_dependencies(self) -> None:
        """Test that @parameter can have its own dependencies."""

        class Config:
            @resource
            def host() -> str:
                return "localhost"

            @parameter
            def database_url(host: str):
                """This parameter depends on host but returns nothing useful."""
                return f"postgresql://{host}/db"  # Return value is ignored

            @resource
            def connection_string(database_url: str) -> str:
                return f"Connected to: {database_url}"

        root = resolve(Config)(database_url="postgresql://prod-server/mydb")
        assert root.connection_string == "Connected to: postgresql://prod-server/mydb"

    def test_parameter_without_base_value_raises_error(self) -> None:
        """Test that accessing a @parameter without providing a base value raises NotImplementedError."""

        class Config:
            @parameter
            def database_url(): ...

            @resource
            def connection_string(database_url: str) -> str:
                return f"Connected to: {database_url}"

        root = resolve(Config)
        try:
            _ = root.connection_string
            assert False, "Expected NotImplementedError"
        except NotImplementedError:
            pass

    def test_parameter_equivalent_to_empty_patches(self) -> None:
        """Test that @parameter is equivalent to @patches returning empty collection."""

        class WithParameter:
            @parameter
            def value(): ...

        class WithEmptyPatches:
            @patches
            def value():
                return ()

        root_param = resolve(WithParameter)(value=42)
        root_patches = resolve(WithEmptyPatches)(value=42)

        assert root_param.value == 42
        assert root_patches.value == 42

    def test_parameter_multiple_injections(self) -> None:
        """Test that multiple @parameter resources can be injected together."""

        class Config:
            @parameter
            def host(): ...

            @parameter
            def port(): ...

            @resource
            def url(host: str, port: int) -> str:
                return f"http://{host}:{port}"

        root = resolve(Config)(host="example.com", port=8080)
        assert root.url == "http://example.com:8080"

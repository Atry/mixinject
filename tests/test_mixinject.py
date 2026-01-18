import sys
import tempfile
from pathlib import Path
from typing import Callable

import pytest

from mixinject import (
    _MergerDefinition,
    Merger,
    CachedProxy,
    InstanceMixin,
    InstanceProxy,
    _NestedMixinSymbol,
    _RootSymbol,
    SymbolSentinel,
    LexicalScope,
    _PackageDefinition,
    _MixinDefinition,
    Proxy,
    RelativeReference,
    StaticProxy,
    _ResourceDefinition,
    _SinglePatchDefinition,
    ChainMapSentinel,
    merge,
    extern,
    patch,
    patch_many,
    resource,
    evaluate,
    scope,
    _parse_package,
    WeakCachedScope,
)
from mixinject import RootMixin, NestedMixin

R = RelativeReference

FIXTURES_DIR = str(Path(__file__).parent / "fixtures")


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


def _empty_mixin() -> NestedMixin:
    """Create a minimal dependency graph for testing."""
    proxy_def = _empty_definition()
    root_symbol = _empty_root_symbol(proxy_def)
    nested_symbol = _empty_nested_symbol(root_symbol, proxy_def)
    root_mixin = RootMixin(symbol=root_symbol)
    return NestedMixin(
        outer=root_mixin,
        symbol=nested_symbol,
        name="test",
    )


class TestSimpleResource:
    """Test basic resource definition and resolution."""

    def test_simple_resource_no_dependencies(self) -> None:
        @scope()
        class Namespace:
            @resource
            def greeting() -> str:
                return "Hello"

        root = evaluate(Namespace)
        assert root.greeting == "Hello"

    def test_resource_with_dependency(self) -> None:
        @scope()
        class Namespace:
            @resource
            def name() -> str:
                return "World"

            @resource
            def greeting(name: str) -> str:
                return f"Hello, {name}!"

        root = evaluate(Namespace)
        assert root.greeting == "Hello, World!"

    def test_multiple_dependencies(self) -> None:
        @scope()
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

        root = evaluate(Namespace)
        assert root.combined == "First and Second"


class TestPatch:
    """Test patch decorator."""

    def test_single_patch(self) -> None:
        @scope()
        class Root:
            @scope()
            class Base:
                @resource
                def value() -> int:
                    return 10

            @scope()
            class Patcher:
                @patch
                def value() -> Callable[[int], int]:
                    return lambda x: x * 2

            @scope(
                extend=[
                    R(levels_up=0, path=("Base",)),
                    R(levels_up=0, path=("Patcher",)),
                ]
            )
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.value == 20

    def test_multiple_patches(self) -> None:
        @scope()
        class Root:
            @scope()
            class Base:
                @resource
                def value() -> int:
                    return 10

            @scope()
            class Patch1:
                @patch
                def value() -> Callable[[int], int]:
                    return lambda x: x + 5

            @scope()
            class Patch2:
                @patch
                def value() -> Callable[[int], int]:
                    return lambda x: x + 3

            @scope(
                extend=[
                    R(levels_up=0, path=("Base",)),
                    R(levels_up=0, path=("Patch1",)),
                    R(levels_up=0, path=("Patch2",)),
                ]
            )
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.value == 18


class TestPatches:
    """Test patches decorator (multiple patches from single callable)."""

    def test_patches_decorator(self) -> None:
        @scope()
        class Root:
            @scope()
            class Base:
                @resource
                def value() -> int:
                    return 10

            @scope()
            class Patcher:
                @patch_many
                def value() -> tuple[Callable[[int], int], ...]:
                    return ((lambda x: x + 5), (lambda x: x + 3))

            @scope(
                extend=[
                    R(levels_up=0, path=("Base",)),
                    R(levels_up=0, path=("Patcher",)),
                ]
            )
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.value == 18


class TestLexicalScope:
    """Test lexical scope lookup (same name parameter)."""

    def test_same_name_lookup_via_nested_scope(self) -> None:
        @scope()
        class Outer:
            @resource
            def counter() -> int:
                return 0

            @scope()
            class Inner:
                @resource
                def counter(counter: int) -> int:
                    return counter + 1

        root = evaluate(Outer)
        assert root.counter == 0
        assert root.Inner.counter == 1


class TestInstanceProxy:
    """Test InstanceProxy created via StaticProxy.__call__."""

    def test_instance_proxy_single_value(self) -> None:
        base_proxy = CachedProxy(mixins={}, mixin=_empty_mixin())
        proxy = base_proxy(foo="bar")
        assert isinstance(proxy, InstanceProxy)
        assert proxy.foo == "bar"

    def test_instance_proxy_multiple_values(self) -> None:
        base_proxy = CachedProxy(mixins={}, mixin=_empty_mixin())
        proxy = base_proxy(foo="bar", count=42, flag=True)
        assert isinstance(proxy, InstanceProxy)
        assert proxy.foo == "bar"
        assert proxy.count == 42
        assert proxy.flag is True


class TestMerger:
    """Test merge decorator."""

    def test_custom_aggregation(self) -> None:
        @scope()
        class Root:
            @scope()
            class Base:
                @merge
                def tags() -> type[frozenset]:
                    return frozenset

            @scope()
            class Provider1:
                @patch
                def tags() -> str:
                    return "tag1"

            @scope()
            class Provider2:
                @patch
                def tags() -> str:
                    return "tag2"

            @scope(
                extend=[
                    R(levels_up=0, path=("Base",)),
                    R(levels_up=0, path=("Provider1",)),
                    R(levels_up=0, path=("Provider2",)),
                ]
            )
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.tags == frozenset({"tag1", "tag2"})


class TestUnionMount:
    """Test union mount semantics using @scope to combine namespaces."""

    def test_union_mount_multiple_namespaces(self) -> None:
        @scope()
        class Root:
            @scope()
            class Namespace1:
                @resource
                def foo() -> str:
                    return "foo_value"

            @scope()
            class Namespace2:
                @resource
                def bar() -> str:
                    return "bar_value"

            @scope(
                extend=[
                    R(levels_up=0, path=("Namespace1",)),
                    R(levels_up=0, path=("Namespace2",)),
                ]
            )
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.foo == "foo_value"
        assert root.Combined.bar == "bar_value"

    def test_union_mount_with_dependencies_across_namespaces(self) -> None:
        @scope()
        class Root:
            @scope()
            class Namespace1:
                @resource
                def base_value() -> str:
                    return "base"

            @scope(
                extend=[
                    R(levels_up=0, path=("Namespace1",)),
                ]
            )
            class Namespace2:
                @extern
                def base_value() -> str: ...

                @resource
                def combined(base_value: str) -> str:
                    return f"{base_value}_combined"

        root = evaluate(Root)
        assert root.Namespace2.combined == "base_combined"

    def test_deduplicated_tags_from_docstring(self) -> None:
        """Test union mounting with @scope(extend=...) to combine branches."""

        @scope()
        class Root:
            @scope()
            class branch0:
                @merge
                def deduplicated_tags() -> type[frozenset]:
                    return frozenset

            @scope()
            class branch1:
                @patch
                def deduplicated_tags() -> str:
                    return "tag1"

                @resource
                def another_dependency() -> str:
                    return "dependency_value"

            @scope()
            class branch2:
                @extern
                def another_dependency() -> str: ...

                @patch
                def deduplicated_tags(another_dependency: str) -> str:
                    return f"tag2_{another_dependency}"

            @scope(
                extend=[
                    R(levels_up=0, path=("branch0",)),
                    R(levels_up=0, path=("branch1",)),
                    R(levels_up=0, path=("branch2",)),
                ]
            )
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.deduplicated_tags == frozenset(
            {"tag1", "tag2_dependency_value"}
        )

    def test_union_mount_point_from_docstring(self) -> None:
        """Test union mounting with @scope(extend=...) to combine scope resources."""

        @scope()
        class Root:
            @scope()
            class branch1:
                @resource
                def foo() -> str:
                    return "foo"

            @scope()
            class branch2:
                @extern
                def foo() -> str: ...

                @resource
                def bar(foo: str) -> str:
                    return f"{foo}_bar"

            @scope(
                extend=[
                    R(levels_up=0, path=("branch1",)),
                    R(levels_up=0, path=("branch2",)),
                ]
            )
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.foo == "foo"
        assert root.Combined.bar == "foo_bar"


class TestExtendInstanceProxyProhibition:
    """Test that extend cannot reference a path through InstanceProxy."""

    def test_extend_instance_proxy_raises_type_error(self) -> None:
        """Extending from an InstanceProxy should raise TypeError."""

        @scope()
        class Root:
            @scope()
            class MyOuter:
                @extern
                def i() -> int: ...

                @resource
                def foo(i: int) -> str:
                    return f"foo_{i}"

            @resource
            def my_instance(MyOuter: Proxy) -> Proxy:
                return MyOuter(i=42)

            # This should fail because my_instance is an InstanceProxy
            @scope(
                extend=[
                    R(levels_up=0, path=("my_instance",)),
                ]
            )
            class Invalid:
                pass

        with pytest.raises(TypeError, match="Cannot extend through InstanceProxy"):
            root = evaluate(Root)
            _ = root.Invalid.foo

    def test_extend_path_through_instance_proxy_raises_type_error(self) -> None:
        """Extending from a path through InstanceProxy should raise TypeError."""

        @scope()
        class Root:
            @scope()
            class MyOuter:
                @extern
                def i() -> int: ...

                @scope()
                class MyInner:
                    @resource
                    def foo() -> str:
                        return "inner_foo"

            @resource
            def my_instance(MyOuter: Proxy) -> Proxy:
                return MyOuter(i=42)

            # This should fail because my_instance is an InstanceProxy,
            # even though MyInner is a StaticProxy
            @scope(
                extend=[
                    R(levels_up=0, path=("my_instance", "MyInner")),
                ]
            )
            class Invalid:
                pass

        with pytest.raises(TypeError, match="Cannot extend through InstanceProxy"):
            root = evaluate(Root)
            _ = root.Invalid.foo

    def test_extend_within_instance_proxy_sibling_allowed(self) -> None:
        """Extending a sibling scope within the same InstanceProxy is allowed.

        The prohibition is on the NAVIGATION PATH of extend references, not on
        whether the extending scope is defined inside an InstanceProxy.

        Here, `root.my_instance` is an InstanceProxy, but `Inner1` extends `Inner2`
        via a sibling reference `R(levels_up=0, path=("Inner2",))`. This path doesn't
        traverse through any InstanceProxy - it's a direct sibling reference within
        the same scope.
        """

        @scope()
        class Root:
            @scope()
            class MyOuter:
                @extern
                def i() -> int: ...

                @scope()
                class Inner2:
                    @resource
                    def base_value() -> int:
                        return 100

                @scope(extend=(R(levels_up=0, path=("Inner2",)),))
                class Inner1:
                    @patch
                    def base_value(i: int) -> Callable[[int], int]:
                        return lambda x: x + i

            @resource
            def my_instance(MyOuter: Proxy) -> Proxy:
                return MyOuter(i=42)

        root = evaluate(Root)

        # Accessing via InstanceProxy should work because the extend reference
        # ("Inner2",) is a sibling reference that doesn't traverse through InstanceProxy
        # Inner1 extends Inner2, so Inner1 has base_value from Inner2, patched by Inner1
        assert root.my_instance.Inner2.base_value == 100
        assert root.my_instance.Inner1.base_value == 142  # 100 + 42 (patched)


class TestScalaStylePathDependentTypes:
    """Test composing multiple path-dependent scopes - a pattern Scala cannot express.

    Scala supports extending a SINGLE path-dependent type (from val or object):

    ```scala
    val object1 = MyOuter(1)        // or: object object1 extends MyOuter(1)
    object MyObjectA extends object1.MyInner { ... }  // OK, result = 111
    ```

    But Scala forbids mixing MULTIPLE path-dependent types:

    ```scala
    val object1 = MyOuter(1)
    val object2 = MyOuter(2)
    // ERROR: trait MyInner is extended twice
    // ERROR: conflicting base types object1.MyInner and object2.MyInner
    object MyObjectA extends object1.MyInner with object2.MyInner { ... }
    ```

    Mixinject takes a different trade-off:
    - Forbids extend through InstanceProxy (val-like) entirely
    - But allows composing MULTIPLE scopes via static @scope with lexical scoping

    This test demonstrates the multi-instance pattern using static scopes.
    Result: 100 + (10 + 1 + 2) = 113
    """

    def test_path_dependent_mixin_linearization(self) -> None:
        """Test composing multiple path-dependent scopes that share underlying definitions.

        Uses mixinject's features:
        - @scope with extend for composing scopes
        - @extern for declaring external dependencies
        - Lexical scope lookup (parameter `i` resolved from outer scope)
        - ReversedPath to distinguish object1.MyInner from object2.MyInner

        Note: Unlike InstanceProxy which captures kwargs at runtime, static @scope
        requires each scope to provide its own patches with local dependencies.
        """

        @scope()
        class Root:
            @scope()
            class Base:
                @resource
                def foo() -> int:
                    return 10

            # object1 and object2 are scopes that provide different `i` values
            # Each has its own MyInner that extends Base and adds a patch using local i
            @scope()
            class object1:
                @resource
                def i() -> int:
                    return 1

                @scope(extend=(R(levels_up=1, path=("Base",)),))
                class MyInner:
                    @patch
                    def foo(i: int) -> Callable[[int], int]:
                        return lambda x: x + i

            @scope()
            class object2:
                @resource
                def i() -> int:
                    return 2

                @scope(extend=(R(levels_up=1, path=("Base",)),))
                class MyInner:
                    @patch
                    def foo(i: int) -> Callable[[int], int]:
                        return lambda x: x + i

            # MyObjectA extends object1.MyInner, object2.MyInner and adds its own patch
            @scope(
                extend=(
                    R(levels_up=0, path=("object1", "MyInner")),
                    R(levels_up=0, path=("object2", "MyInner")),
                )
            )
            class MyObjectA:
                @patch
                def foo() -> Callable[[int], int]:
                    return lambda x: 100 + x

        root = evaluate(Root)

        # mixin is the runtime access path:
        #   root.object1.MyInner.mixin == ("MyInner", "object1", "root")
        #   root.object2.MyInner.mixin == ("MyInner", "object2", "root")
        object1_inner = root.object1.MyInner
        object2_inner = root.object2.MyInner
        assert object1_inner.mixin != object2_inner.mixin

        # foo = 10 (Base) + 1 (object1.MyInner) + 2 (object2.MyInner) + 100 (MyObjectA) = 113
        assert root.MyObjectA.foo == 113


class TestInstanceProxyReversedPath:
    """Test that InstanceProxy has correct mixin with InstanceChildMixin."""

    def test_instance_proxy_nested_access_has_instance_mixin_in_path(
        self,
    ) -> None:
        """When accessing nested proxy through InstanceProxy, path should use InstanceChildMixin."""

        @scope()
        class Root:
            @scope()
            class MyOuter:
                @extern
                def i() -> int: ...

                @scope()
                class MyInner:
                    @resource
                    def foo(i: int) -> str:
                        return f"foo_{i}"

            @resource
            def my_instance(MyOuter: Proxy) -> Proxy:
                return MyOuter(i=42)

        root = evaluate(Root)

        # Access MyInner through the InstanceProxy
        my_instance = root.my_instance
        my_inner = my_instance.MyInner

        # The mixin should be InstanceChildMixin to distinguish from static path
        assert isinstance(my_instance.mixin, InstanceMixin)

        # Verify the resource works correctly
        assert my_inner.foo == "foo_42"


class TestSymbolSharing:
    """Test that _Symbol instances are shared among mixins from the same _MixinDefinition."""

    def test_symbol_shared_across_different_instance_args(self) -> None:
        """_Symbol should be shared when accessing Inner through different Outer instances."""

        @scope()
        class Root:
            @scope()
            class Outer:
                @extern
                def arg() -> str: ...

                @scope()
                class Inner:
                    @resource
                    def value(arg: str) -> str:
                        return f"value_{arg}"

        root = evaluate(Root)

        inner1 = root.Outer(arg="v1").Inner
        inner2 = root.Outer(arg="v2").Inner

        # Use the mixin's symbol directly
        symbol1 = inner1.mixin.symbol
        symbol2 = inner2.mixin.symbol

        assert symbol1 is symbol2

    @pytest.mark.xfail(
        reason="BUG: InstanceChildMixin and ChildMixin have separate intern_pools, "
        "causing instance path to create new ChildMixin with SymbolSentinel.MERGED "
        "instead of reusing the one created via static path."
    )
    def test_symbol_shared_between_instance_and_static_access(self) -> None:
        """_Symbol should be shared between InstanceProxy and StaticProxy access paths.

        .. todo:: Fix _ProxySemigroup.create to share symbol between instance and static paths.

            Currently when accessing Inner via instance path (root.Outer(arg="v1").Inner),
            the access_path_outer is an InstanceChildMixin which has its own
            intern_pool. When _ProxySemigroup.create checks this intern_pool, it doesn't
            find the existing ChildMixin (created via resolve for static
            path), so it creates a new one with symbol=SymbolSentinel.MERGED.

            The fix should ensure that InstanceChildMixin delegates to its
            prototype's intern_pool, or that _ProxySemigroup.create uses the prototype's
            intern_pool when access_path_outer is an InstanceChildMixin.
        """

        @scope()
        class Root:
            @scope()
            class Outer:
                @extern
                def arg() -> str: ...

                @scope()
                class Inner:
                    @resource
                    def value(arg: str) -> str:
                        return f"value_{arg}"

        root = evaluate(Root)

        instance_inner = root.Outer(arg="v1").Inner
        static_inner = root.Outer.Inner

        # Use the mixin's symbol directly
        instance_symbol = instance_inner.mixin.symbol
        static_symbol = static_inner.mixin.symbol

        assert instance_symbol is static_symbol

    @pytest.mark.xfail(
        reason="BUG: Same issue as test_symbol_shared_between_instance_and_static_access. "
        "InstanceChildMixin has separate intern_pool from ChildMixin, "
        "causing different symbol values for the same underlying scope definition."
    )
    def test_symbol_shared_when_scope_extends_another(self) -> None:
        """_Symbol should be shared when accessing Inner through extending scopes.

        .. todo:: Fix _ProxySemigroup.create to share symbol across extending scopes.

            When object1 extends Outer, accessing Inner through both paths should yield
            the same symbol since they refer to the same Python class definition
            (Root.Outer.Inner). Currently, each InstanceChildMixin has its own
            intern_pool, leading to separate ChildMixin instances with different
            symbol values (SymbolSentinel.MERGED vs real _Symbol).

            The fix should ensure that all access paths to the same scope definition
            share the same _Symbol instance.
        """

        @scope()
        class Root:
            @scope()
            class Outer:
                @extern
                def arg() -> str: ...

                @scope()
                class Inner:
                    @resource
                    def value(arg: str) -> str:
                        return f"value_{arg}"

            @scope(extend=(R(levels_up=1, path=("Outer",)),))
            class object1:
                @extern
                def arg() -> str: ...

        root = evaluate(Root)

        outer_inner = root.Outer(arg="v1").Inner
        object1_inner = root.object1(arg="v2").Inner

        # Use the mixin's symbol directly
        outer_symbol = outer_inner.mixin.symbol
        object1_symbol = object1_inner.mixin.symbol

        # Both should share the same symbol since they access the same Inner definition
        assert outer_symbol is object1_symbol
        # Neither should be MERGED sentinel - they should have real _Symbol
        assert outer_symbol is not SymbolSentinel.SYNTHETIC
        assert object1_symbol is not SymbolSentinel.SYNTHETIC


class TestProxyAsSymlink:
    """Test Proxy return values acting as symlinks."""

    def test_proxy_symlink(self) -> None:
        base_proxy = CachedProxy(mixins={}, mixin=_empty_mixin())
        inner_proxy = base_proxy(inner_value="inner")

        @scope()
        class Namespace:
            @resource
            def linked() -> Proxy:
                return inner_proxy

        root = evaluate(Namespace)
        assert root.linked.inner_value == "inner"


class TestModuleParsing:
    """Test module and package parsing with pkgutil/importlib."""

    def test_parse_module_returns_lazy_mapping_for_package(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import regular_pkg

            scope_def = _parse_package(
                regular_pkg,
                get_module_proxy_class=lambda _: CachedProxy,
            )
            assert isinstance(scope_def, _PackageDefinition)
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("regular_pkg", None)
            sys.modules.pop("regular_pkg.child", None)

    def test_lazy_submodule_import(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import regular_pkg

            root = evaluate(regular_pkg)
            assert "regular_pkg.child" not in sys.modules
            _ = root.child
            assert "regular_pkg.child" in sys.modules
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("regular_pkg", None)
            sys.modules.pop("regular_pkg.child", None)

    def test_resolve_root_with_package(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import regular_pkg

            root = evaluate(regular_pkg)
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

            scope_def = _parse_package(
                regular_mod,
                get_module_proxy_class=lambda _: CachedProxy,
            )
            assert isinstance(scope_def, _MixinDefinition)
            assert not isinstance(scope_def, _PackageDefinition)
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("regular_mod", None)

    def test_namespace_package_discovery(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import ns_pkg

            assert hasattr(ns_pkg, "__path__")
            scope_def = _parse_package(
                ns_pkg,
                get_module_proxy_class=lambda _: CachedProxy,
            )
            assert isinstance(scope_def, _PackageDefinition)

            root = evaluate(ns_pkg)
            assert root.mod_a.value_a == "a"
            assert root.mod_b.base == "base"
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("ns_pkg", None)
            sys.modules.pop("ns_pkg.mod_a", None)
            sys.modules.pop("ns_pkg.mod_b", None)

    def test_namespace_package_submodule_with_internal_dependency(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import ns_pkg

            root = evaluate(ns_pkg)
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
                scope_def = _parse_package(
                    ns_pkg,
                    get_module_proxy_class=lambda _: CachedProxy,
                )
                assert isinstance(scope_def, _PackageDefinition)

                root = evaluate(ns_pkg)
                assert root.mod_a.value_a == "a"
                assert root.mod_b.base == "base"
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
        base_proxy = CachedProxy(mixins={}, mixin=_empty_mixin())
        proxy = base_proxy(foo="foo_value")

        # Call proxy with new kwargs to add additional values
        new_proxy = proxy(bar="bar_value")

        assert new_proxy.foo == "foo_value"  # from first call
        assert new_proxy.bar == "bar_value"  # from second call

    def test_proxy_call_multiple_kwargs(self) -> None:
        """Test calling Proxy with multiple new kwargs."""
        base_proxy = CachedProxy(mixins={}, mixin=_empty_mixin())
        proxy = base_proxy(x=1, y=2)

        # Call to add new values (z and w)
        new_proxy = proxy(z=3, w=4)

        assert new_proxy.x == 1  # from first call
        assert new_proxy.y == 2  # from first call
        assert new_proxy.z == 3  # from second call
        assert new_proxy.w == 4  # from second call

    def test_proxy_call_injected_values_accessible(self) -> None:
        """Test that values injected via Proxy call are accessible as resources."""
        # Create empty proxy and inject values via call
        proxy = CachedProxy(mixins={}, mixin=_empty_mixin())(
            config={"db": "postgres"}
        )(timeout=30)

        # Injected values should be accessible
        assert proxy.config == {"db": "postgres"}
        assert proxy.timeout == 30

    def test_proxy_call_provides_endo_only_base_value(self) -> None:
        """Test Proxy callable providing base value for parameter pattern.

        Pattern:
        - Use @extern to declare a symbol that will be provided at runtime
        - Provide the value via Proxy.__call__
        - Other resources can depend on the parameter
        """

        @scope()
        class Config:
            @extern
            def db_config() -> dict:
                """Parameter to be provided via Proxy.__call__"""
                ...

            @resource
            def connection_string(db_config: dict) -> str:
                """Depends on db_config parameter"""
                return f"{db_config['host']}:{db_config['port']}"

        root = evaluate(Config)(db_config={"host": "localhost", "port": "5432"})
        assert root.db_config == {"host": "localhost", "port": "5432"}
        assert root.connection_string == "localhost:5432"

    def test_proxy_call_returns_instance_proxy(self) -> None:
        """Test that calling a StaticProxy returns an InstanceProxy."""

        class Value:
            pass

        v1, v2 = Value(), Value()

        # CachedProxy.__call__ should return InstanceProxy
        cached = CachedProxy(mixins={}, mixin=_empty_mixin())
        instance1 = cached(x=v1)
        assert isinstance(instance1, InstanceProxy)
        assert instance1.x is v1

        # Calling InstanceProxy again should return another InstanceProxy
        instance2 = instance1(y=v2)
        assert isinstance(instance2, InstanceProxy)
        assert instance2.x is v1
        assert instance2.y is v2

        # WeakCachedScope.__call__ should also return InstanceProxy
        weak = WeakCachedScope(mixins={}, mixin=_empty_mixin())
        weak_instance = weak(x=v1)
        assert isinstance(weak_instance, InstanceProxy)
        assert weak_instance.x is v1

    def test_proxy_call_creates_fresh_instance(self) -> None:
        """Test that calling a Proxy creates a new instance without modifying the original."""
        base_proxy = CachedProxy(mixins={}, mixin=_empty_mixin())
        proxy1 = base_proxy(a=1)

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

        @scope()
        class Namespace:
            @resource
            def foo() -> str:
                return "foo"

        root = evaluate(Namespace)
        result = dir(root)
        assert isinstance(result, list)

    def test_dir_includes_names(self) -> None:
        """Test that __dir__ includes all resource names."""

        @scope()
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

        root = evaluate(Namespace)
        result = dir(root)
        assert "resource1" in result
        assert "resource2" in result
        assert "resource3" in result

    def test_dir_includes_builtin_attrs(self) -> None:
        """Test that __dir__ includes builtin attributes."""

        @scope()
        class Namespace:
            @resource
            def foo() -> str:
                return "foo"

        root = evaluate(Namespace)
        result = dir(root)
        assert "__class__" in result
        assert "__getitem__" in result
        assert "mixins" in result

    def test_dir_is_sorted(self) -> None:
        """Test that __dir__ returns a sorted list."""

        @scope()
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

        root = evaluate(Namespace)
        result = dir(root)
        assert result == sorted(result)

    def test_dir_with_multiple_mixins(self) -> None:
        """Test __dir__ with multiple mixins providing different resources."""

        @scope()
        class Root:
            @scope()
            class Namespace1:
                @resource
                def foo() -> str:
                    return "foo"

            @scope()
            class Namespace2:
                @resource
                def bar() -> str:
                    return "bar"

            @scope(
                extend=[
                    R(levels_up=0, path=("Namespace1",)),
                    R(levels_up=0, path=("Namespace2",)),
                ]
            )
            class Combined:
                pass

        root = evaluate(Root)
        result = dir(root.Combined)
        assert "foo" in result
        assert "bar" in result

    def test_dir_deduplicates_names(self) -> None:
        """Test that __dir__ deduplicates resource names when multiple mixins provide the same name."""

        @scope()
        class Root:
            @scope()
            class Namespace1:
                @resource
                def shared() -> str:
                    return "from_ns1"

            @scope()
            class Namespace2:
                @patch
                def shared() -> Callable[[str], str]:
                    return lambda s: s + "_patched"

            @scope(
                extend=[
                    R(levels_up=0, path=("Namespace1",)),
                    R(levels_up=0, path=("Namespace2",)),
                ]
            )
            class Combined:
                pass

        root = evaluate(Root)
        result = dir(root.Combined)
        assert result.count("shared") == 1

    def test_dir_works_with_cached_proxy(self) -> None:
        """Test __dir__ works with CachedProxy subclass."""

        @scope()
        class Namespace:
            @resource
            def cached_resource() -> str:
                return "cached"

        root = evaluate(Namespace)
        result = dir(root)
        assert "cached_resource" in result

    def test_dir_works_with_weak_cached_scope(self) -> None:
        """Test __dir__ works with WeakCachedScope subclass."""

        @scope()
        class Namespace:
            @resource
            def weak_resource() -> str:
                return "weak"

        root = evaluate(Namespace)
        result = dir(root)
        assert "weak_resource" in result

    def test_dir_accessible_via_getattr(self) -> None:
        """Test that all resource names from __dir__ are accessible via getattr."""

        @scope()
        class Namespace:
            @resource
            def accessible1() -> str:
                return "a1"

            @resource
            def accessible2() -> str:
                return "a2"

        root = evaluate(Namespace)
        assert "accessible1" in dir(root)
        assert "accessible2" in dir(root)
        assert getattr(root, "accessible1") == "a1"
        assert getattr(root, "accessible2") == "a2"


class TestParameter:
    """Test parameter decorator as syntactic sugar for empty patches."""

    def test_parameter_with_keyword_argument_mixin(self) -> None:
        """Test that @extern registers a resource name and accepts injected values."""

        @scope()
        class Config:
            @extern
            def database_url(): ...

            @resource
            def connection_string(database_url: str) -> str:
                return f"Connected to: {database_url}"

        root = evaluate(Config)(database_url="postgresql://localhost/mydb")
        assert root.connection_string == "Connected to: postgresql://localhost/mydb"

    def test_parameter_with_dependencies(self) -> None:
        """Test that @extern can have its own dependencies."""

        @scope()
        class Config:
            @resource
            def host() -> str:
                return "localhost"

            @extern
            def database_url(host: str):
                """This parameter depends on host but returns nothing useful."""
                return f"postgresql://{host}/db"  # Return value is ignored

            @resource
            def connection_string(database_url: str) -> str:
                return f"Connected to: {database_url}"

        root = evaluate(Config)(database_url="postgresql://prod-server/mydb")
        assert root.connection_string == "Connected to: postgresql://prod-server/mydb"

    def test_parameter_without_base_value_raises_error(self) -> None:
        """Test that accessing a @extern without providing a base value raises NotImplementedError."""

        @scope()
        class Config:
            @extern
            def database_url(): ...

            @resource
            def connection_string(database_url: str) -> str:
                return f"Connected to: {database_url}"

        root = evaluate(Config)
        try:
            _ = root.connection_string
            assert False, "Expected NotImplementedError"
        except NotImplementedError:
            pass

    def test_parameter_equivalent_to_empty_patches(self) -> None:
        """Test that @extern is equivalent to @patch_many returning empty collection."""

        @scope()
        class WithParameter:
            @extern
            def value(): ...

        @scope()
        class WithEmptyPatches:
            @patch_many
            def value():
                return ()

        root_param = evaluate(WithParameter)(value=42)
        root_patches = evaluate(WithEmptyPatches)(value=42)

        assert root_param.value == 42
        assert root_patches.value == 42

    def test_parameter_multiple_injections(self) -> None:
        """Test that multiple @extern resources can be injected together."""

        @scope()
        class Config:
            @extern
            def host(): ...

            @extern
            def port(): ...

            @resource
            def url(host: str, port: int) -> str:
                return f"http://{host}:{port}"

        root = evaluate(Config)(host="example.com", port=8080)
        assert root.url == "http://example.com:8080"

    def test_patch_with_identity_endo_equivalent_to_parameter(self) -> None:
        """Test that @patch with identity endo is equivalent to @extern.

        Pattern:
        - @patch returning `lambda x: x` (identity function) without dependencies
        - Should behave identically to @extern

        The identity endo passes through the base value unchanged, effectively
        making it a placeholder that accepts injected values.
        """

        @scope()
        class WithParameter:
            @extern
            def value(): ...

            @resource
            def doubled(value: int) -> int:
                return value * 2

        @scope()
        class WithIdentityPatch:
            @patch
            def value() -> Callable[[int], int]:
                return lambda x: x

            @resource
            def doubled(value: int) -> int:
                return value * 2

        # Both should work identically when value is injected
        root_param = evaluate(WithParameter)(value=21)
        root_patch = evaluate(WithIdentityPatch)(value=21)

        assert root_param.value == 21
        assert root_patch.value == 21
        assert root_param.doubled == 42
        assert root_patch.doubled == 42

    def test_patch_with_identity_endo_requires_base_value(self) -> None:
        """Test that @patch with identity endo requires a base value (like @extern)."""

        @scope()
        class WithIdentityPatch:
            @patch
            def config() -> Callable[[dict], dict]:
                return lambda x: x

        root = evaluate(WithIdentityPatch)
        try:
            _ = root.config
            assert False, "Expected NotImplementedError"
        except NotImplementedError:
            pass


class TestProxySemigroupMixin:
    """Test _ProxySemigroup.create correctly assigns mixin."""

    def test_extended_proxy_has_distinct_mixin(self) -> None:
        """Extended proxy should have its own mixin, not primary's.

        When scope B extends scope A via extend=, B.mixin should be
        distinct from A.mixin because they represent different
        positions in the topology (B is accessed as "B", not "A").
        """

        @scope()
        class Root:
            @scope()
            class Base:
                @resource
                def value() -> int:
                    return 10

            @scope(extend=(R(levels_up=0, path=("Base",)),))
            class Extended:
                @resource
                def doubled(value: int) -> int:
                    return value * 2

        root = evaluate(Root)

        # The extended proxy should have its own unique mixin
        # that represents its access path ("Extended", "Root"), not Base's path
        base_mixin = root.Base.mixin
        extended_mixin = root.Extended.mixin

        # This should pass - Extended has its own mixin
        assert extended_mixin is not base_mixin, (
            "Extended proxy should have its own mixin, "
            "not share with Base proxy"
        )

    def test_nested_scope_in_extended_has_distinct_mixin(self) -> None:
        """Nested scope in Extended should have different mixin than in Base.

        Expected behavior:
        - base_another.mixin.name == "Another"
        - extended_another.mixin.name == "Another"
        - base_another.mixin.outer.name == "Base"
        - extended_another.mixin.outer.name == "Extended"
        """

        @scope()
        class Root:
            @scope()
            class Base:
                @resource
                def value() -> int:
                    return 10

                @scope()
                class Another:
                    @resource
                    def nested_value() -> str:
                        return "nested"

                    @patch
                    def nested_value2() -> str:
                        return lambda x: x * 3

            @scope()
            class Base2:
                @scope()
                class Another:
                    @patch
                    def nested_value() -> str:
                        return lambda x: x * 3

                    @resource
                    def nested_value2() -> str:
                        return "nested"

            @scope(
                extend=(R(levels_up=0, path=("Base",)), R(levels_up=0, path=("Base2",)))
            )
            class Extended:
                @resource
                def doubled(value: int) -> int:
                    return value * 2

        root = evaluate(Root)

        # Access Another through Base and Extended
        base_another = root.Base.Another
        extended_another = root.Extended.Another
        assert root.Extended.Another.nested_value2 == "nestednestednested"
        assert root.Extended.Another.nested_value == "nestednestednested"

        # Print actual values for debugging
        print(
            f"\nbase_another.mixin.name = {base_another.mixin.name!r}"
        )
        print(
            f"extended_another.mixin.name = {extended_another.mixin.name!r}"
        )
        print(
            f"base_another.mixin.outer.name = {base_another.mixin.outer.name!r}"
        )
        print(
            f"extended_another.mixin.outer.name = {extended_another.mixin.outer.name!r}"
        )

        # Verify name for both
        assert base_another.mixin.name == "Another"
        assert extended_another.mixin.name == "Another"

        # Verify outer.name
        assert base_another.mixin.outer.name == "Base"
        assert extended_another.mixin.outer.name == "Extended"

        # Verify the nested resource is still accessible (with patch applied)
        assert extended_another.nested_value == "nestednestednested"

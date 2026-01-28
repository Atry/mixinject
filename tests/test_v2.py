"""Tests for MixinV2 and ScopeV2 implementation."""

import sys
from pathlib import Path
from typing import Callable

import pytest

from mixinject import (
    evaluate,
    resource,
    scope,
    eager,
    local,
    extend,
    extern,
    merge,
    patch,
    patch_many,
    RelativeReference,
    _parse_package,
    PackageScopeDefinition,
    ScopeDefinition,
)
from mixinject.v2 import (
    MixinV2,
    ScopeV2,
    evaluate_v2,
)

R = RelativeReference

FIXTURES_DIR = str(Path(__file__).parent / "fixtures")


class TestBasicConstruction:
    """Test basic ScopeV2 construction and attribute access."""

    def test_simple_resource_no_dependencies(self) -> None:
        @scope
        class Namespace:
            @resource
            def greeting() -> str:
                return "Hello"

        root = evaluate_v2(Namespace)
        assert isinstance(root, ScopeV2)
        assert root.greeting == "Hello"

    def test_resource_with_dependency(self) -> None:
        @scope
        class Namespace:
            @resource
            def name() -> str:
                return "World"

            @resource
            def greeting(name: str) -> str:
                return f"Hello, {name}!"

        root = evaluate_v2(Namespace)
        assert root.greeting == "Hello, World!"

    def test_multiple_dependencies(self) -> None:
        @scope
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

        root = evaluate_v2(Namespace)
        assert root.combined == "First and Second"

    def test_getitem_access(self) -> None:
        @scope
        class Namespace:
            @resource
            def value() -> int:
                return 42

        root = evaluate_v2(Namespace)
        assert root["value"] == 42

    def test_attribute_error_for_missing(self) -> None:
        @scope
        class Namespace:
            @resource
            def existing() -> str:
                return "exists"

        root = evaluate_v2(Namespace)
        with pytest.raises(AttributeError):
            _ = root.nonexistent

    def test_key_error_for_missing(self) -> None:
        @scope
        class Namespace:
            @resource
            def existing() -> str:
                return "exists"

        root = evaluate_v2(Namespace)
        with pytest.raises(KeyError):
            _ = root["nonexistent"]


class TestLazyEvaluation:
    """Test that resources are evaluated lazily by default."""

    def test_lazy_evaluation_default(self) -> None:
        call_count = 0

        @scope
        class Namespace:
            @resource
            def lazy_resource() -> str:
                nonlocal call_count
                call_count += 1
                return "evaluated"

        root = evaluate_v2(Namespace)

        # Resource should not be evaluated yet
        assert call_count == 0

        # Access the resource
        result = root.lazy_resource
        assert result == "evaluated"
        assert call_count == 1

        # Second access should use cached value
        result2 = root.lazy_resource
        assert result2 == "evaluated"
        assert call_count == 1  # Still 1, no re-evaluation

    def test_children_contains_mixin_v2_for_lazy(self) -> None:
        @scope
        class Namespace:
            @resource
            def lazy() -> str:
                return "value"

        root = evaluate_v2(Namespace)

        # Lazy resources should work correctly when accessed
        # (ScopeV2 is now fully lazy - children are created on demand)
        result = root.lazy
        assert result == "value"


class TestEagerEvaluation:
    """Test is_eager=True semantics."""

    def test_eager_evaluation(self) -> None:
        call_count = 0

        @scope
        class Namespace:
            @eager
            @resource
            def eager_resource() -> str:
                nonlocal call_count
                call_count += 1
                return "evaluated"

        # Eager resources are evaluated immediately during scope construction
        root = evaluate_v2(Namespace)
        assert call_count == 1  # Evaluated during construction

        # First access returns cached value (already evaluated)
        result = root.eager_resource
        assert result == "evaluated"
        assert call_count == 1  # Still 1

        # Subsequent access returns same cached value
        result2 = root.eager_resource
        assert result2 == "evaluated"
        assert call_count == 1  # Still 1

    def test_children_contains_value_for_eager(self) -> None:
        @scope
        class Namespace:
            @eager
            @resource
            def eager() -> str:
                return "value"

        root = evaluate_v2(Namespace)

        # Eager resources should return the evaluated value
        # (In lazy ScopeV2, eager evaluation happens on first access)
        result = root.eager
        assert result == "value"


class TestLocalResources:
    """Test is_local=True semantics."""

    def test_local_resource_not_in_children(self) -> None:
        @scope
        class Namespace:
            @local
            @resource
            def local_resource() -> str:
                return "local"

            @resource
            def public_resource() -> str:
                return "public"

        root = evaluate_v2(Namespace)

        # Local resource should not be accessible via __getattr__
        with pytest.raises(AttributeError):
            _ = root.local_resource

        # Public resource should be accessible
        assert root.public_resource == "public"

    def test_local_resource_raises_attribute_error(self) -> None:
        @scope
        class Namespace:
            @local
            @resource
            def local_resource() -> str:
                return "local"

        root = evaluate_v2(Namespace)

        with pytest.raises(AttributeError):
            _ = root.local_resource

    def test_local_resource_raises_key_error(self) -> None:
        @scope
        class Namespace:
            @local
            @resource
            def local_resource() -> str:
                return "local"

        root = evaluate_v2(Namespace)

        with pytest.raises(KeyError):
            _ = root["local_resource"]

    def test_local_resource_accessible_as_dependency(self) -> None:
        @scope
        class Namespace:
            @local
            @resource
            def api_endpoint() -> str:
                return "/api/v1"

            @resource
            def full_url(api_endpoint: str) -> str:
                return f"https://example.com{api_endpoint}"

        root = evaluate_v2(Namespace)

        # Local resource is accessible indirectly via dependency
        assert root.full_url == "https://example.com/api/v1"

        # But not directly
        with pytest.raises(AttributeError):
            _ = root.api_endpoint


class TestCircularDependencies:
    """Test circular dependency handling."""

    def test_construction_succeeds_with_circular_deps(self) -> None:
        """ScopeV2 construction should succeed even with circular dependencies."""

        @scope
        class Namespace:
            @resource
            def a(b: str) -> str:
                return f"a({b})"

            @resource
            def b(a: str) -> str:
                return f"b({a})"

        # Construction should succeed - no evaluation happens yet
        root = evaluate_v2(Namespace)
        assert isinstance(root, ScopeV2)

    def test_circular_evaluation_raises_recursion_error(self) -> None:
        """Evaluating truly circular resources should cause RecursionError."""

        @scope
        class Namespace:
            @resource
            def a(b: str) -> str:
                return f"a({b})"

            @resource
            def b(a: str) -> str:
                return f"b({a})"

        root = evaluate_v2(Namespace)

        # Attempting to evaluate should cause RecursionError
        with pytest.raises(RecursionError):
            _ = root.a


class TestNestedScopes:
    """Test nested scope construction."""

    def test_nested_scope_creation(self) -> None:
        @scope
        class Inner:
            @resource
            def inner_value() -> int:
                return 42

        @scope
        class Outer:
            inner = Inner

        root = evaluate_v2(Outer)

        # Access nested scope
        inner_scope = root.inner
        assert isinstance(inner_scope, ScopeV2)
        assert inner_scope.inner_value == 42

    def test_nested_scope_with_outer_dependency(self) -> None:
        @scope
        class Outer:
            @resource
            def multiplier() -> int:
                return 10

            @scope
            class inner:
                @resource
                def base() -> int:
                    return 5

                @resource
                def computed(base: int, multiplier: int) -> int:
                    return base * multiplier

        root = evaluate_v2(Outer)

        assert root.inner.computed == 50


class TestUnionMount:
    """Test union mounting of multiple namespaces."""

    def test_union_mount_complementary(self) -> None:
        @scope
        class First:
            @resource
            def a() -> str:
                return "a"

        @scope
        class Second:
            @resource
            def b() -> str:
                return "b"

        root = evaluate_v2(First, Second)
        assert root.a == "a"
        assert root.b == "b"


class TestV2VsV1Parity:
    """Test that V2 produces same results as V1 for basic cases."""

    def test_simple_resource_parity(self) -> None:
        @scope
        class Namespace:
            @resource
            def greeting() -> str:
                return "Hello"

        v1_root = evaluate(Namespace)
        v2_root = evaluate_v2(Namespace)

        assert v1_root.greeting == v2_root.greeting

    def test_dependency_parity(self) -> None:
        @scope
        class Namespace:
            @resource
            def name() -> str:
                return "World"

            @resource
            def greeting(name: str) -> str:
                return f"Hello, {name}!"

        v1_root = evaluate(Namespace)
        v2_root = evaluate_v2(Namespace)

        assert v1_root.greeting == v2_root.greeting

    def test_nested_scope_parity(self) -> None:
        @scope
        class Outer:
            @resource
            def value() -> int:
                return 10

            @scope
            class inner:
                @resource
                def doubled(value: int) -> int:
                    return value * 2

        v1_root = evaluate(Outer)
        v2_root = evaluate_v2(Outer)

        assert v1_root.inner.doubled == v2_root.inner.doubled


class TestPatch:
    """Test patch decorator (ported from V1)."""

    def test_single_patch(self) -> None:
        @scope
        class Root:
            @scope
            class Base:
                @resource
                def value() -> int:
                    return 10

            @scope
            class Patcher:
                @patch
                def value() -> Callable[[int], int]:
                    return lambda x: x * 2

            @extend(
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Patcher",)),
            )
            @scope
            class Combined:
                pass

        root = evaluate_v2(Root)
        assert root.Combined.value == 20

    def test_multiple_patches(self) -> None:
        @scope
        class Root:
            @scope
            class Base:
                @resource
                def value() -> int:
                    return 10

            @scope
            class Patch1:
                @patch
                def value() -> Callable[[int], int]:
                    return lambda x: x + 5

            @scope
            class Patch2:
                @patch
                def value() -> Callable[[int], int]:
                    return lambda x: x + 3

            @extend(
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Patch1",)),
                R(levels_up=0, path=("Patch2",)),
            )
            @scope
            class Combined:
                pass

        root = evaluate_v2(Root)
        assert root.Combined.value == 18


class TestPatches:
    """Test patches decorator (multiple patches from single callable, ported from V1)."""

    def test_patches_decorator(self) -> None:
        @scope
        class Root:
            @scope
            class Base:
                @resource
                def value() -> int:
                    return 10

            @scope
            class Patcher:
                @patch_many
                def value() -> tuple[Callable[[int], int], ...]:
                    return ((lambda x: x + 5), (lambda x: x + 3))

            @extend(
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Patcher",)),
            )
            @scope
            class Combined:
                pass

        root = evaluate_v2(Root)
        assert root.Combined.value == 18


class TestCapturedScopes:
    """Test lexical scope lookup (same name parameter, ported from V1)."""

    def test_same_name_lookup_via_nested_scope(self) -> None:
        @scope
        class Outer:
            @resource
            def counter() -> int:
                return 0

            @scope
            class Inner:
                @resource
                def counter(counter: int) -> int:
                    return counter + 1

        root = evaluate_v2(Outer)
        assert root.counter == 0
        assert root.Inner.counter == 1


class TestMerger:
    """Test merge decorator (ported from V1)."""

    def test_custom_aggregation(self) -> None:
        @scope
        class Root:
            @scope
            class Base:
                @merge
                def tags() -> type[frozenset]:
                    return frozenset

            @scope
            class Provider1:
                @patch
                def tags() -> str:
                    return "tag1"

            @scope
            class Provider2:
                @patch
                def tags() -> str:
                    return "tag2"

            @extend(
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Provider1",)),
                R(levels_up=0, path=("Provider2",)),
            )
            @scope
            class Combined:
                pass

        root = evaluate_v2(Root)
        assert root.Combined.tags == frozenset({"tag1", "tag2"})


class TestUnionMountV2:
    """Test union mount semantics using @scope to combine namespaces (ported from V1)."""

    def test_union_mount_multiple_namespaces(self) -> None:
        @scope
        class Root:
            @scope
            class Namespace1:
                @resource
                def foo() -> str:
                    return "foo_value"

            @scope
            class Namespace2:
                @resource
                def bar() -> str:
                    return "bar_value"

            @extend(
                R(levels_up=0, path=("Namespace1",)),
                R(levels_up=0, path=("Namespace2",)),
            )
            @scope
            class Combined:
                pass

        root = evaluate_v2(Root)
        assert root.Combined.foo == "foo_value"
        assert root.Combined.bar == "bar_value"

    def test_union_mount_with_dependencies_across_namespaces(self) -> None:
        @scope
        class Root:
            @scope
            class Namespace1:
                @resource
                def base_value() -> str:
                    return "base"

            @extend(R(levels_up=0, path=("Namespace1",)))
            @scope
            class Namespace2:
                @extern
                def base_value() -> str: ...

                @resource
                def combined(base_value: str) -> str:
                    return f"{base_value}_combined"

        root = evaluate_v2(Root)
        assert root.Namespace2.combined == "base_combined"

    def test_deduplicated_tags_from_docstring(self) -> None:
        """Test union mounting with @scope(extend=...) to combine branches."""

        @scope
        class Root:
            @scope
            class branch0:
                @merge
                def deduplicated_tags() -> type[frozenset]:
                    return frozenset

            @scope
            class branch1:
                @patch
                def deduplicated_tags() -> str:
                    return "tag1"

                @resource
                def another_dependency() -> str:
                    return "dependency_value"

            @scope
            class branch2:
                @extern
                def another_dependency() -> str: ...

                @patch
                def deduplicated_tags(another_dependency: str) -> str:
                    return f"tag2_{another_dependency}"

            @extend(
                R(levels_up=0, path=("branch0",)),
                R(levels_up=0, path=("branch1",)),
                R(levels_up=0, path=("branch2",)),
            )
            @scope
            class Combined:
                pass

        root = evaluate_v2(Root)
        assert root.Combined.deduplicated_tags == frozenset(
            {"tag1", "tag2_dependency_value"}
        )

    def test_union_mount_point_from_docstring(self) -> None:
        """Test union mounting with @scope(extend=...) to combine scope resources."""

        @scope
        class Root:
            @scope
            class branch1:
                @resource
                def foo() -> str:
                    return "foo"

            @scope
            class branch2:
                @extern
                def foo() -> str: ...

                @resource
                def bar(foo: str) -> str:
                    return f"{foo}_bar"

            @extend(
                R(levels_up=0, path=("branch1",)),
                R(levels_up=0, path=("branch2",)),
            )
            @scope
            class Combined:
                pass

        root = evaluate_v2(Root)
        assert root.Combined.foo == "foo"
        assert root.Combined.bar == "foo_bar"

    def test_evaluate_root_level_union_mount_different_names(self) -> None:
        """Test union mounting at root level with different resource names."""

        @scope
        class Namespace1:
            @resource
            def foo() -> str:
                return "foo_value"

        @scope
        class Namespace2:
            @resource
            def bar() -> str:
                return "bar_value"

        root = evaluate_v2(Namespace1, Namespace2)
        assert root.foo == "foo_value"
        assert root.bar == "bar_value"

    def test_evaluate_root_level_union_mount_with_extern(self) -> None:
        """Test union mounting at root level with @extern dependency."""

        @scope
        class Provider:
            @resource
            def base_value() -> str:
                return "base"

        @scope
        class Consumer:
            @extern
            def base_value() -> str: ...

            @resource
            def derived(base_value: str) -> str:
                return f"{base_value}_derived"

        root = evaluate_v2(Provider, Consumer)
        assert root.base_value == "base"
        assert root.derived == "base_derived"

    def test_evaluate_root_level_union_mount_with_merge_and_patch(self) -> None:
        """Test union mounting at root level with @merge and @patch."""

        @scope
        class MergerNamespace:
            @merge
            def tags() -> type[frozenset]:
                return frozenset

        @scope
        class PatchNamespace1:
            @patch
            def tags() -> str:
                return "tag1"

        @scope
        class PatchNamespace2:
            @patch
            def tags() -> str:
                return "tag2"

        root = evaluate_v2(MergerNamespace, PatchNamespace1, PatchNamespace2)
        assert root.tags == frozenset({"tag1", "tag2"})


class TestExtendNameResolution:
    """Test that names from extended scopes can be resolved without @extern (ported from V1)."""

    def test_extend_allows_name_resolution_without_extern(self) -> None:
        """Extended scope should be able to resolve names from base scope."""

        @scope
        class Root:
            @scope
            class Base:
                @resource
                def base_value() -> int:
                    return 42

            @extend(R(levels_up=0, path=("Base",)))
            @scope
            class Extended:
                @resource
                def doubled(base_value: int) -> int:
                    return base_value * 2

        root = evaluate_v2(Root)
        assert root.Extended.base_value == 42
        assert root.Extended.doubled == 84


class TestScalaStylePathDependentTypes:
    """Test composing multiple path-dependent scopes (ported from V1)."""

    def test_path_dependent_symbol_linearization(self) -> None:
        """Test composing multiple path-dependent scopes that share underlying definitions."""

        @scope
        class Root:
            @scope
            class Base:
                @resource
                def foo() -> int:
                    return 10

            @scope
            class object1:
                @resource
                def i() -> int:
                    return 1

                @extend(R(levels_up=1, path=("Base",)))
                @scope
                class MyInner:
                    @patch
                    def foo(i: int) -> Callable[[int], int]:
                        return lambda x: x + i

            @scope
            class object2:
                @resource
                def i() -> int:
                    return 2

                @extend(R(levels_up=1, path=("Base",)))
                @scope
                class MyInner:
                    @patch
                    def foo(i: int) -> Callable[[int], int]:
                        return lambda x: x + i

            @extend(
                R(levels_up=0, path=("object1", "MyInner")),
                R(levels_up=0, path=("object2", "MyInner")),
            )
            @scope
            class MyObjectA:
                @patch
                def foo() -> Callable[[int], int]:
                    return lambda x: 100 + x

        root = evaluate_v2(Root)

        # foo = 10 (Base) + 1 (object1.MyInner) + 2 (object2.MyInner) + 100 (MyObjectA) = 113
        assert root.MyObjectA.foo == 113


class TestModuleParsing:
    """Test module and package parsing with pkgutil/importlib (ported from V1)."""

    def test_parse_module_returns_lazy_mapping_for_package(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import regular_pkg

            scope_def = _parse_package(regular_pkg)
            assert isinstance(scope_def, PackageScopeDefinition)
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("regular_pkg", None)
            sys.modules.pop("regular_pkg.child", None)

    def test_lazy_submodule_import(self) -> None:
        """Test that V2 imports ONE level of children per .evaluated call.

        V2's laziness semantics:
        - evaluate_v2(nested_pkg) → imports nested_pkg, iterates its children (imports child)
        - root.child → triggers child_mixin.evaluated, which iterates child_symbol
          and imports its children (grandchild)

        Each .evaluated call imports exactly ONE level of children.
        This is the expected behavior per the plan.
        """
        # Clean up any previously imported modules first
        for mod in list(sys.modules.keys()):
            if mod.startswith("nested_pkg"):
                sys.modules.pop(mod, None)

        sys.path.insert(0, FIXTURES_DIR)
        try:
            import nested_pkg

            root = evaluate_v2(nested_pkg)

            # After evaluate_v2(nested_pkg):
            # - nested_pkg is imported
            # - nested_pkg.child is imported (direct child, via symbol["child"])
            # - nested_pkg.child.grandchild is NOT imported (grandchild not iterated yet)
            assert "nested_pkg.child.grandchild" not in sys.modules

            # Access child - this triggers child_mixin.evaluated which iterates
            # the child symbol and imports its children (grandchild)
            _ = root.child.child_value

            # Now grandchild IS imported because we evaluated the child scope
            # This is expected: each .evaluated imports ONE level of children
            assert "nested_pkg.child.grandchild" in sys.modules

            # Access grandchild explicitly works
            _ = root.child.grandchild.grandchild_value

        finally:
            sys.path.remove(FIXTURES_DIR)
            for mod in list(sys.modules.keys()):
                if mod.startswith("nested_pkg"):
                    sys.modules.pop(mod, None)

    def test_resolve_root_with_package(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import regular_pkg

            root = evaluate_v2(regular_pkg)
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

            scope_def = _parse_package(regular_mod)
            assert isinstance(scope_def, ScopeDefinition)
            assert not isinstance(scope_def, PackageScopeDefinition)
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("regular_mod", None)

    def test_namespace_package_discovery(self) -> None:
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import ns_pkg

            assert hasattr(ns_pkg, "__path__")
            scope_def = _parse_package(ns_pkg)
            assert isinstance(scope_def, PackageScopeDefinition)

            root = evaluate_v2(ns_pkg)
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

            root = evaluate_v2(ns_pkg)
            assert root.mod_b.base == "base"
            assert root.mod_b.derived == "base_derived"
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("ns_pkg", None)
            sys.modules.pop("ns_pkg.mod_a", None)
            sys.modules.pop("ns_pkg.mod_b", None)


class TestMissingDependency:
    """Test error handling when a resource depends on a non-existent dependency (ported from V1)."""

    def test_resource_with_missing_dependency(self) -> None:
        """A resource that depends on a non-existent resource should raise an error."""

        @scope
        class Namespace:
            @resource
            def greeting(nonexistent_dependency: str) -> str:
                return f"Hello, {nonexistent_dependency}!"

        root = evaluate_v2(Namespace)
        with pytest.raises(LookupError, match="greeting.*nonexistent_dependency"):
            _ = root.greeting


class TestFixtureReference:
    """Test FixtureReference with pytest fixture-style same-name skip semantics (ported from V1)."""

    def test_same_name_skips_first_match(self) -> None:
        """FixtureReference with name == current_key skips first match."""

        @scope
        class Outer:
            @resource
            def counter() -> int:
                return 0

            @scope
            class Inner:
                @resource
                def counter(counter: int) -> int:
                    return counter + 1

        root = evaluate_v2(Outer)
        assert root.counter == 0
        assert root.Inner.counter == 1

    def test_different_name_does_normal_lookup(self) -> None:
        """FixtureReference with name != current_key does normal lexical lookup."""

        @scope
        class Outer:
            @resource
            def other() -> str:
                return "other_value"

            @scope
            class Inner:
                @resource
                def something(other: str) -> str:
                    return f"got_{other}"

        root = evaluate_v2(Outer)
        assert root.Inner.something == "got_other_value"

    def test_fixture_reference_same_name_at_root_level(self) -> None:
        """FixtureReference same-name at deeper level still works if outer has the name."""

        @scope
        class Root:
            @resource
            def value() -> int:
                return 10

            @scope
            class Level1:
                @resource
                def value(value: int) -> int:
                    return value + 1

                @scope
                class Level2:
                    @resource
                    def value(value: int) -> int:
                        return value + 1

        root = evaluate_v2(Root)
        assert root.value == 10
        assert root.Level1.value == 11
        assert root.Level1.Level2.value == 12


class TestExtendWithModule:
    """Test @extend decorator with module references (ported from V1)."""

    def test_extend_references_sibling_modules(self) -> None:
        """Test that @extend can reference sibling modules in a package."""
        sys.path.insert(0, FIXTURES_DIR)
        try:
            import union_mount

            root = evaluate_v2(union_mount)

            # Test that combined scope has resources from all branches
            assert root.combined.deduplicated_tags == frozenset(
                {"tag1", "tag2_dependency_value"}
            )

            # union_mount_point is a semigroup scope merged from all branches
            assert root.combined.union_mount_point.foo == "foo"
            assert root.combined.union_mount_point.bar == "foo_bar"

            # another_dependency comes from branch1
            assert root.combined.another_dependency == "dependency_value"

        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("union_mount", None)
            sys.modules.pop("union_mount.branch0", None)
            sys.modules.pop("union_mount.branch1", None)
            sys.modules.pop("union_mount.branch2", None)

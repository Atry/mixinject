"""Tests for Mixin and Scope implementation."""

import sys
from pathlib import Path
from typing import Callable

import pytest

from mixinject import (
    resource,
    scope,
    eager,
    public,
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
from mixinject.runtime import (
    Mixin,
    Scope,
    evaluate,
)

R = RelativeReference

FIXTURES_DIR = str(Path(__file__).parent / "fixtures")


class TestBasicConstruction:
    """Test basic Scope construction and attribute access."""

    def test_simple_resource_no_dependencies(self) -> None:
        @scope
        class Namespace:
            @public
            @resource
            def greeting() -> str:
                return "Hello"

        root = evaluate(Namespace)
        assert isinstance(root, Scope)
        assert root.greeting == "Hello"

    def test_resource_with_dependency(self) -> None:
        @scope
        class Namespace:
            @resource
            def name() -> str:
                return "World"

            @public
            @resource
            def greeting(name: str) -> str:
                return f"Hello, {name}!"

        root = evaluate(Namespace)
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

            @public
            @resource
            def combined(first: str, second: str) -> str:
                return f"{first} and {second}"

        root = evaluate(Namespace)
        assert root.combined == "First and Second"

    def test_getitem_access(self) -> None:
        @scope
        class Namespace:
            @public
            @resource
            def value() -> int:
                return 42

        root = evaluate(Namespace)
        assert root["value"] == 42

    def test_attribute_error_for_missing(self) -> None:
        @scope
        class Namespace:
            @public
            @resource
            def existing() -> str:
                return "exists"

        root = evaluate(Namespace)
        with pytest.raises(AttributeError):
            _ = root.nonexistent

    def test_key_error_for_missing(self) -> None:
        @scope
        class Namespace:
            @public
            @resource
            def existing() -> str:
                return "exists"

        root = evaluate(Namespace)
        with pytest.raises(KeyError):
            _ = root["nonexistent"]


class TestLazyEvaluation:
    """Test that resources are evaluated lazily by default."""

    def test_lazy_evaluation_default(self) -> None:
        call_count = 0

        @scope
        class Namespace:
            @public
            @resource
            def lazy_resource() -> str:
                nonlocal call_count
                call_count += 1
                return "evaluated"

        root = evaluate(Namespace)

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
            @public
            @resource
            def lazy() -> str:
                return "value"

        root = evaluate(Namespace)

        # Lazy resources should work correctly when accessed
        # (Scope is now fully lazy - children are created on demand)
        result = root.lazy
        assert result == "value"


class TestEagerEvaluation:
    """Test is_eager=True semantics."""

    def test_eager_evaluation(self) -> None:
        call_count = 0

        @scope
        class Namespace:
            @public
            @eager
            @resource
            def eager_resource() -> str:
                nonlocal call_count
                call_count += 1
                return "evaluated"

        # Eager resources are evaluated immediately during scope construction
        root = evaluate(Namespace)
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
            @public
            @eager
            @resource
            def eager() -> str:
                return "value"

        root = evaluate(Namespace)

        # Eager resources should return the evaluated value
        # (In lazy Scope, eager evaluation happens on first access)
        result = root.eager
        assert result == "value"


class TestPublicResources:
    """Test is_public=True semantics (private by default)."""

    def test_private_resource_not_in_children(self) -> None:
        @scope
        class Namespace:
            @resource
            def private_resource() -> str:
                return "private"

            @public
            @resource
            def public_resource() -> str:
                return "public"

        root = evaluate(Namespace)

        # Private resource (no @public) should not be accessible via __getattr__
        with pytest.raises(AttributeError):
            _ = root.private_resource

        # Public resource should be accessible
        assert root.public_resource == "public"

    def test_private_resource_raises_attribute_error(self) -> None:
        @scope
        class Namespace:
            @resource
            def private_resource() -> str:
                return "private"

        root = evaluate(Namespace)

        with pytest.raises(AttributeError):
            _ = root.private_resource

    def test_private_resource_raises_key_error(self) -> None:
        @scope
        class Namespace:
            @resource
            def private_resource() -> str:
                return "private"

        root = evaluate(Namespace)

        with pytest.raises(KeyError):
            _ = root["private_resource"]

    def test_private_resource_accessible_as_dependency(self) -> None:
        @scope
        class Namespace:
            @resource
            def api_endpoint() -> str:
                return "/api/v1"

            @public
            @resource
            def full_url(api_endpoint: str) -> str:
                return f"https://example.com{api_endpoint}"

        root = evaluate(Namespace)

        # Private resource is accessible indirectly via dependency
        assert root.full_url == "https://example.com/api/v1"

        # But not directly
        with pytest.raises(AttributeError):
            _ = root.api_endpoint


class TestCircularDependencies:
    """Test circular dependency handling."""

    def test_construction_succeeds_with_circular_deps(self) -> None:
        """Scope construction should succeed even with circular dependencies."""

        @scope
        class Namespace:
            @public
            @resource
            def a(b: str) -> str:
                return f"a({b})"

            @public
            @resource
            def b(a: str) -> str:
                return f"b({a})"

        # Construction should succeed - no evaluation happens yet
        root = evaluate(Namespace)
        assert isinstance(root, Scope)

    def test_circular_evaluation_raises_recursion_error(self) -> None:
        """Evaluating truly circular resources should cause RecursionError."""

        @scope
        class Namespace:
            @public
            @resource
            def a(b: str) -> str:
                return f"a({b})"

            @public
            @resource
            def b(a: str) -> str:
                return f"b({a})"

        root = evaluate(Namespace)

        # Attempting to evaluate should cause RecursionError
        with pytest.raises(RecursionError):
            _ = root.a


class TestNestedScopes:
    """Test nested scope construction."""

    def test_nested_scope_creation(self) -> None:
        @public
        @scope
        class Inner:
            @public
            @resource
            def inner_value() -> int:
                return 42

        @scope
        class Outer:
            inner = Inner

        root = evaluate(Outer)

        # Access nested scope
        inner_scope = root.inner
        assert isinstance(inner_scope, Scope)
        assert inner_scope.inner_value == 42

    def test_nested_scope_with_outer_dependency(self) -> None:
        @scope
        class Outer:
            @public
            @resource
            def multiplier() -> int:
                return 10

            @public
            @scope
            class inner:
                @resource
                def base() -> int:
                    return 5

                @public
                @resource
                def computed(base: int, multiplier: int) -> int:
                    return base * multiplier

        root = evaluate(Outer)

        assert root.inner.computed == 50


class TestUnionMount:
    """Test union mounting of multiple namespaces."""

    def test_union_mount_complementary(self) -> None:
        @scope
        class First:
            @public
            @resource
            def a() -> str:
                return "a"

        @scope
        class Second:
            @public
            @resource
            def b() -> str:
                return "b"

        root = evaluate(First, Second)
        assert root.a == "a"
        assert root.b == "b"


class TestPatch:
    """Test patch decorator (ported from V1)."""

    def test_single_patch(self) -> None:
        @scope
        class Root:
            @scope
            class Base:
                @public
                @resource
                def value() -> int:
                    return 10

            @scope
            class Patcher:
                @patch
                def value() -> Callable[[int], int]:
                    return lambda x: x * 2

            @extend(
                R(de_bruijn_index=0, path=("Base",)),
                R(de_bruijn_index=0, path=("Patcher",)),
            )
            @public
            @scope
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.value == 20

    def test_multiple_patches(self) -> None:
        @scope
        class Root:
            @scope
            class Base:
                @public
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
                R(de_bruijn_index=0, path=("Base",)),
                R(de_bruijn_index=0, path=("Patch1",)),
                R(de_bruijn_index=0, path=("Patch2",)),
            )
            @public
            @scope
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.value == 18


class TestPatches:
    """Test patches decorator (multiple patches from single callable, ported from V1)."""

    def test_patches_decorator(self) -> None:
        @scope
        class Root:
            @scope
            class Base:
                @public
                @resource
                def value() -> int:
                    return 10

            @scope
            class Patcher:
                @patch_many
                def value() -> tuple[Callable[[int], int], ...]:
                    return ((lambda x: x + 5), (lambda x: x + 3))

            @extend(
                R(de_bruijn_index=0, path=("Base",)),
                R(de_bruijn_index=0, path=("Patcher",)),
            )
            @public
            @scope
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.value == 18


class TestCapturedScopes:
    """Test lexical scope lookup (same name parameter, ported from V1)."""

    def test_same_name_lookup_via_nested_scope(self) -> None:
        @scope
        class Outer:
            @public
            @resource
            def counter() -> int:
                return 0

            @public
            @scope
            class Inner:
                @public
                @resource
                def counter(counter: int) -> int:
                    return counter + 1

        root = evaluate(Outer)
        assert root.counter == 0
        assert root.Inner.counter == 1


class TestMerger:
    """Test merge decorator (ported from V1)."""

    def test_custom_aggregation(self) -> None:
        @scope
        class Root:
            @scope
            class Base:
                @public
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
                R(de_bruijn_index=0, path=("Base",)),
                R(de_bruijn_index=0, path=("Provider1",)),
                R(de_bruijn_index=0, path=("Provider2",)),
            )
            @public
            @scope
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.tags == frozenset({"tag1", "tag2"})


class TestUnionMount:
    """Test union mount semantics using @scope to combine namespaces (ported from V1)."""

    def test_union_mount_multiple_namespaces(self) -> None:
        @scope
        class Root:
            @scope
            class Namespace1:
                @public
                @resource
                def foo() -> str:
                    return "foo_value"

            @scope
            class Namespace2:
                @public
                @resource
                def bar() -> str:
                    return "bar_value"

            @extend(
                R(de_bruijn_index=0, path=("Namespace1",)),
                R(de_bruijn_index=0, path=("Namespace2",)),
            )
            @public
            @scope
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.foo == "foo_value"
        assert root.Combined.bar == "bar_value"

    def test_union_mount_with_dependencies_across_namespaces(self) -> None:
        @scope
        class Root:
            @scope
            class Namespace1:
                @public
                @resource
                def base_value() -> str:
                    return "base"

            @extend(R(de_bruijn_index=0, path=("Namespace1",)))
            @public
            @scope
            class Namespace2:
                @extern
                def base_value() -> str: ...

                @public
                @resource
                def combined(base_value: str) -> str:
                    return f"{base_value}_combined"

        root = evaluate(Root)
        assert root.Namespace2.combined == "base_combined"

    def test_deduplicated_tags_from_docstring(self) -> None:
        """Test union mounting with @scope(extend=...) to combine branches."""

        @scope
        class Root:
            @scope
            class branch0:
                @public
                @merge
                def deduplicated_tags() -> type[frozenset]:
                    return frozenset

            @scope
            class branch1:
                @patch
                def deduplicated_tags() -> str:
                    return "tag1"

                @public
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
                R(de_bruijn_index=0, path=("branch0",)),
                R(de_bruijn_index=0, path=("branch1",)),
                R(de_bruijn_index=0, path=("branch2",)),
            )
            @public
            @scope
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.deduplicated_tags == frozenset(
            {"tag1", "tag2_dependency_value"}
        )

    def test_union_mount_point_from_docstring(self) -> None:
        """Test union mounting with @scope(extend=...) to combine scope resources."""

        @scope
        class Root:
            @scope
            class branch1:
                @public
                @resource
                def foo() -> str:
                    return "foo"

            @scope
            class branch2:
                @extern
                def foo() -> str: ...

                @public
                @resource
                def bar(foo: str) -> str:
                    return f"{foo}_bar"

            @extend(
                R(de_bruijn_index=0, path=("branch1",)),
                R(de_bruijn_index=0, path=("branch2",)),
            )
            @public
            @scope
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.foo == "foo"
        assert root.Combined.bar == "foo_bar"

    def test_evaluate_root_level_union_mount_different_names(self) -> None:
        """Test union mounting at root level with different resource names."""

        @scope
        class Namespace1:
            @public
            @resource
            def foo() -> str:
                return "foo_value"

        @scope
        class Namespace2:
            @public
            @resource
            def bar() -> str:
                return "bar_value"

        root = evaluate(Namespace1, Namespace2)
        assert root.foo == "foo_value"
        assert root.bar == "bar_value"

    def test_evaluate_root_level_union_mount_with_extern(self) -> None:
        """Test union mounting at root level with @extern dependency."""

        @scope
        class Provider:
            @public
            @resource
            def base_value() -> str:
                return "base"

        @scope
        class Consumer:
            @extern
            def base_value() -> str: ...

            @public
            @resource
            def derived(base_value: str) -> str:
                return f"{base_value}_derived"

        root = evaluate(Provider, Consumer)
        assert root.base_value == "base"
        assert root.derived == "base_derived"

    def test_evaluate_root_level_union_mount_with_merge_and_patch(self) -> None:
        """Test union mounting at root level with @merge and @patch."""

        @scope
        class MergerNamespace:
            @public
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

        root = evaluate(MergerNamespace, PatchNamespace1, PatchNamespace2)
        assert root.tags == frozenset({"tag1", "tag2"})


class TestExtendNameResolution:
    """Test that names from extended scopes can be resolved without @extern (ported from V1)."""

    def test_extend_allows_name_resolution_without_extern(self) -> None:
        """Extended scope should be able to resolve names from base scope."""

        @scope
        class Root:
            @scope
            class Base:
                @public
                @resource
                def base_value() -> int:
                    return 42

            @extend(R(de_bruijn_index=0, path=("Base",)))
            @public
            @scope
            class Extended:
                @public
                @resource
                def doubled(base_value: int) -> int:
                    return base_value * 2

        root = evaluate(Root)
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
                @public
                @resource
                def foo() -> int:
                    return 10

            @scope
            class object1:
                @public
                @resource
                def i() -> int:
                    return 1

                @extend(R(de_bruijn_index=1, path=("Base",)))
                @scope
                class MyInner:
                    @patch
                    def foo(i: int) -> Callable[[int], int]:
                        return lambda x: x + i

            @scope
            class object2:
                @public
                @resource
                def i() -> int:
                    return 2

                @extend(R(de_bruijn_index=1, path=("Base",)))
                @scope
                class MyInner:
                    @patch
                    def foo(i: int) -> Callable[[int], int]:
                        return lambda x: x + i

            @extend(
                R(de_bruijn_index=0, path=("object1", "MyInner")),
                R(de_bruijn_index=0, path=("object2", "MyInner")),
            )
            @public
            @scope
            class MyObjectA:
                @patch
                def foo() -> Callable[[int], int]:
                    return lambda x: 100 + x

        root = evaluate(Root)

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
        - evaluate(nested_pkg) → imports nested_pkg, iterates its children (imports child)
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

            root = evaluate(nested_pkg, modules_public=True)

            # After evaluate(nested_pkg):
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

            root = evaluate(regular_pkg, modules_public=True)
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

            root = evaluate(ns_pkg, modules_public=True)
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

            root = evaluate(ns_pkg, modules_public=True)
            assert root.mod_b.base == "base"
            assert root.mod_b.derived == "base_derived"
        finally:
            sys.path.remove(FIXTURES_DIR)
            sys.modules.pop("ns_pkg", None)
            sys.modules.pop("ns_pkg.mod_a", None)
            sys.modules.pop("ns_pkg.mod_b", None)

    def test_namespace_package_union_mount_multiple_directories(self) -> None:
        """Test namespace packages that span multiple directories (ported from V1)."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            ns_pkg_dir = Path(tmpdir) / "ns_pkg"
            ns_pkg_dir.mkdir()
            (ns_pkg_dir / "mod_c.py").write_text(
                "from mixinject import public, resource\n"
                "value_c = public(resource(lambda: 'c'))\n"
            )

            sys.path.insert(0, FIXTURES_DIR)
            sys.path.insert(0, tmpdir)
            try:
                import ns_pkg

                assert len(ns_pkg.__path__) == 2
                scope_def = _parse_package(ns_pkg)
                assert isinstance(scope_def, PackageScopeDefinition)

                root = evaluate(ns_pkg, modules_public=True)
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


class TestMissingDependency:
    """Test error handling when a resource depends on a non-existent dependency (ported from V1)."""

    def test_resource_with_missing_dependency(self) -> None:
        """A resource that depends on a non-existent resource should raise an error."""

        @scope
        class Namespace:
            @public
            @resource
            def greeting(nonexistent_dependency: str) -> str:
                return f"Hello, {nonexistent_dependency}!"

        root = evaluate(Namespace)
        with pytest.raises(LookupError, match="greeting.*nonexistent_dependency"):
            _ = root.greeting


class TestFixtureReference:
    """Test FixtureReference with pytest fixture-style same-name skip semantics (ported from V1)."""

    def test_same_name_skips_first_match(self) -> None:
        """FixtureReference with name == current_key skips first match."""

        @scope
        class Outer:
            @public
            @resource
            def counter() -> int:
                return 0

            @public
            @scope
            class Inner:
                @public
                @resource
                def counter(counter: int) -> int:
                    return counter + 1

        root = evaluate(Outer)
        assert root.counter == 0
        assert root.Inner.counter == 1

    def test_different_name_does_normal_lookup(self) -> None:
        """FixtureReference with name != current_key does normal lexical lookup."""

        @scope
        class Outer:
            @public
            @resource
            def other() -> str:
                return "other_value"

            @public
            @scope
            class Inner:
                @public
                @resource
                def something(other: str) -> str:
                    return f"got_{other}"

        root = evaluate(Outer)
        assert root.Inner.something == "got_other_value"

    def test_fixture_reference_same_name_at_root_level(self) -> None:
        """FixtureReference same-name at deeper level still works if outer has the name."""

        @scope
        class Root:
            @public
            @resource
            def value() -> int:
                return 10

            @public
            @scope
            class Level1:
                @public
                @resource
                def value(value: int) -> int:
                    return value + 1

                @public
                @scope
                class Level2:
                    @public
                    @resource
                    def value(value: int) -> int:
                        return value + 1

        root = evaluate(Root)
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

            root = evaluate(union_mount)

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


class TestInstanceScope:
    """Test instance scope created via Scope.__call__ (ported from V1 TestInstanceScope)."""

    def test_instance_scope_single_value(self) -> None:
        """Ported from V1: test_instance_scope_single_value"""

        @scope
        class Config:
            @public
            @extern
            def foo() -> str: ...

        base_scope = evaluate(Config)
        instance = base_scope(foo="bar")
        assert isinstance(instance, Scope)
        assert instance.foo == "bar"

    def test_instance_scope_multiple_values(self) -> None:
        """Ported from V1: test_instance_scope_multiple_values"""

        @scope
        class Config:
            @public
            @extern
            def foo() -> str: ...

            @public
            @extern
            def count() -> int: ...

            @public
            @extern
            def flag() -> bool: ...

        base_scope = evaluate(Config)
        instance = base_scope(foo="bar", count=42, flag=True)
        assert isinstance(instance, Scope)
        assert instance.foo == "bar"
        assert instance.count == 42
        assert instance.flag is True


class TestScopeCallable:
    """Test Scope as Callable - dynamic mixin injection (ported from V1 TestScopeCallable)."""

    def test_scope_call_provides_endo_only_base_value(self) -> None:
        """Test Scope callable providing base value for parameter pattern.

        Pattern:
        - Use @extern to declare a symbol that will be provided at runtime
        - Provide the value via Scope.__call__
        - Other resources can depend on the parameter
        """

        @scope
        class Config:
            @extern
            def db_config() -> dict: ...

            @public
            @resource
            def connection_string(db_config: dict) -> str:
                return f"host={db_config['host']}:{db_config['port']}"

        base_scope = evaluate(Config)
        instance = base_scope(db_config={"host": "localhost", "port": 5432})
        assert instance.connection_string == "host=localhost:5432"


class TestInstanceScopeImplementation:
    """Test InstanceScope dataclass implementation details (ported from V1)."""

    def test_instance_scope_kwargs_applies_endofunction_patches(self) -> None:
        """Ported from V1: test_instance_scope_kwargs_applies_endofunction_patches

        When providing a value via __call__, endofunction patches should be applied.
        """
        from mixinject import Endofunction

        @scope
        class Config:

            @public
            @patch
            def greeting() -> Endofunction[str]:
                return lambda s: s + "!"

        base_scope = evaluate(Config)
        instance = base_scope(greeting="Hello")

        # The greeting should be "Hello!" (transformed by the endofunction)
        assert instance.greeting == "Hello!"


class TestSyntheticScopeCallable:
    """Test that inherited scopes (Synthetic) can also be called (ported from V1)."""

    def test_inherited_scope_can_be_called(self) -> None:
        """Ported from V1: test_inherited_scope_can_be_called

        When accessing an inherited scope through @extend, calling it should work.
        """

        @scope
        class Root:
            @scope
            class Base:
                @public
                @scope
                class Inner:
                    @extern
                    def arg() -> str: ...

                    @public
                    @resource
                    def value(arg: str) -> str:
                        return f"value_{arg}"

            @extend(R(de_bruijn_index=0, path=("Base",)))
            @public
            @scope
            class Extended:
                pass

        root = evaluate(Root)

        # Extended inherits Inner from Base
        extended_inner = root.Extended.Inner

        # Calling the inherited scope should work
        instance = extended_inner(arg="test")
        assert instance.value == "value_test"


class TestInstanceScopeNestedAccess:
    """Test nested scope access through instance scopes (ported from V1)."""

    def test_instance_scope_nested_access(self) -> None:
        """Ported from V1: test_instance_scope_nested_access_has_instance_symbol_in_path"""

        @scope
        class Root:
            @public
            @scope
            class MyOuter:
                @extern
                def i() -> int: ...

                @public
                @scope
                class MyInner:
                    @public
                    @resource
                    def foo(i: int) -> str:
                        return f"foo_{i}"

        root = evaluate(Root)

        # Create instance with i=42
        my_instance = root.MyOuter(i=42)
        my_inner = my_instance.MyInner

        # Verify the resource works correctly
        assert my_inner.foo == "foo_42"


class TestDefinitionSharing:
    """Test that Definition instances are shared among mixins (ported from V1)."""

    def test_definition_shared_across_different_instance_args(self) -> None:
        """Ported from V1: test_definition_shared_across_different_instance_args"""

        @scope
        class Root:
            @public
            @scope
            class Outer:
                @extern
                def arg() -> str: ...

                @public
                @scope
                class Inner:
                    @public
                    @resource
                    def value(arg: str) -> str:
                        return f"value_{arg}"

        root = evaluate(Root)

        inner1 = root.Outer(arg="v1").Inner
        inner2 = root.Outer(arg="v2").Inner

        # Verify different values are produced
        assert inner1.value == "value_v1"
        assert inner2.value == "value_v2"


class TestExtendInstanceScopeProhibition:
    """Test that extend cannot reference a path through InstanceScope (ported from V1)."""

    def test_extend_instance_scope_raises_value_error(self) -> None:
        """Extending from a resource returning Scope raises ValueError.

        Scope MixinSymbol cannot coexist with MergerSymbol or PatcherSymbol.
        """

        @scope
        class Root:
            @public
            @scope
            class MyOuter:
                @extern
                def i() -> int: ...

                @public
                @resource
                def foo(i: int) -> str:
                    return f"foo_{i}"

            @resource
            def my_instance(MyOuter: Scope) -> Scope:
                return MyOuter(i=42)

            @extend(R(de_bruijn_index=0, path=("my_instance",)))
            @public
            @scope
            class Extended:
                pass

        root = evaluate(Root)
        with pytest.raises(
            ValueError,
            match="Scope MixinSymbol cannot coexist with MergerSymbol or PatcherSymbol",
        ):
            _ = root.Extended.foo

    def test_extend_path_through_resource_raises_value_error(self) -> None:
        """Extending from a path through a resource raises ValueError.

        The path ("my_instance", "MyInner") tries to navigate through my_instance
        which is a MixinSymbol with MergerDefinition (from @resource), not a scope.
        Symbols with MergerDefinition don't support nested children.
        """

        @scope
        class Root:
            @scope
            class MyOuter:
                @extern
                def i() -> int: ...

                @scope
                class MyInner:
                    @resource
                    def foo() -> str:
                        return "inner_foo"

            @resource
            def my_instance(MyOuter: Scope) -> Scope:
                return MyOuter(i=42)

            # This fails because my_instance is a merger MixinSymbol, not a scope
            @extend(R(de_bruijn_index=0, path=("my_instance", "MyInner")))
            @scope
            class Invalid:
                pass

        with pytest.raises(ValueError, match=r"'my_instance' has no child 'MyInner'"):
            root = evaluate(Root)
            _ = root.Invalid.foo

    def test_extend_within_instance_scope_sibling_allowed(self) -> None:
        """Ported from V1: test_extend_within_instance_scope_sibling_allowed

        Extending a sibling scope within the same InstanceScope is allowed.
        """

        @scope
        class Root:
            @public
            @scope
            class MyOuter:
                @extern
                def i() -> int: ...

                @public
                @scope
                class Inner2:
                    @public
                    @resource
                    def base_value() -> int:
                        return 100

                @extend(R(de_bruijn_index=0, path=("Inner2",)))
                @public
                @scope
                class Inner1:
                    @patch
                    def base_value(i: int) -> Callable[[int], int]:
                        return lambda x: x + i

        root = evaluate(Root)
        my_instance = root.MyOuter(i=42)

        # Accessing via InstanceScope should work because the extend reference
        # ("Inner2",) is a sibling reference that doesn't traverse through InstanceScope
        assert my_instance.Inner2.base_value == 100
        assert my_instance.Inner1.base_value == 142  # 100 + 42 (patched)


class TestExtendNonMixin:
    """Test extending non-Mixin references (potential edge cases, ported from V1)."""

    def test_extend_resource_with_patch(self) -> None:
        """Extending a Resource path with @patch works correctly.

        When @extend is used with a path that leads to a Resource (not a Scope),
        and the extending definition is a @patch, the system correctly resolves
        the base Resource and applies the patch.
        """

        @scope
        class Root:
            @public
            @resource
            def base_value() -> int:
                return 10

            # Extending a Resource (not a Scope) with a patch
            # The resulting merged resource inherits is_public from base_value
            @extend(R(de_bruijn_index=0, path=("base_value",)))
            @patch
            def patched_value() -> Callable[[int], int]:
                return lambda x: x + 1

        root = evaluate(Root)
        # This should work: base_value (10) + patch (+1) = 11
        assert root.patched_value == 11


class TestScopeAsSymlink:
    """Test Scope return values acting as symlinks (ported from V1)."""

    def test_scope_symlink(self) -> None:
        @scope
        class Inner:
            @public
            @extern
            def inner_value() -> str: ...

        inner_scope = evaluate(Inner)(inner_value="inner")

        @scope
        class Namespace:
            @public
            @resource
            def linked() -> Scope:
                return inner_scope

        root = evaluate(Namespace)
        assert root.linked.inner_value == "inner"


class TestScopeDir:
    """Test Scope.__dir__ method (ported from V1)."""

    def test_dir_returns_list(self) -> None:
        """Test that __dir__ returns a list."""

        @scope
        class Namespace:
            @resource
            def foo() -> str:
                return "foo"

        root = evaluate(Namespace)
        result = dir(root)
        assert isinstance(result, list)

    def test_dir_includes_names(self) -> None:
        """Test that __dir__ includes all public resource names."""

        @scope
        class Namespace:
            @public
            @resource
            def resource1() -> str:
                return "r1"

            @public
            @resource
            def resource2() -> str:
                return "r2"

            @public
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

        @scope
        class Namespace:
            @resource
            def foo() -> str:
                return "foo"

        root = evaluate(Namespace)
        result = dir(root)
        assert "__class__" in result
        assert "__call__" in result
        assert "symbol" in result

    def test_dir_is_sorted(self) -> None:
        """Test that __dir__ returns a sorted list."""

        @scope
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

    def test_dir_with_multiple_symbols(self) -> None:
        """Test __dir__ with multiple mixins providing different resources."""

        @scope
        class Root:
            @scope
            class Namespace1:
                @public
                @resource
                def foo() -> str:
                    return "foo"

            @scope
            class Namespace2:
                @public
                @resource
                def bar() -> str:
                    return "bar"

            @extend(
                R(de_bruijn_index=0, path=("Namespace1",)),
                R(de_bruijn_index=0, path=("Namespace2",)),
            )
            @public
            @scope
            class Combined:
                pass

        root = evaluate(Root)
        result = dir(root.Combined)
        assert "foo" in result
        assert "bar" in result

    def test_dir_deduplicates_names(self) -> None:
        """Test that __dir__ deduplicates resource names when multiple mixins provide the same name."""

        @scope
        class Root:
            @scope
            class Namespace1:
                @public
                @resource
                def shared() -> str:
                    return "from_ns1"

            @scope
            class Namespace2:
                @patch
                def shared() -> Callable[[str], str]:
                    return lambda s: s + "_patched"

            @extend(
                R(de_bruijn_index=0, path=("Namespace1",)),
                R(de_bruijn_index=0, path=("Namespace2",)),
            )
            @public
            @scope
            class Combined:
                pass

        root = evaluate(Root)
        result = dir(root.Combined)
        assert result.count("shared") == 1

    def test_dir_accessible_via_getattr(self) -> None:
        """Test that all resource names from __dir__ are accessible via getattr."""

        @scope
        class Namespace:
            @public
            @resource
            def accessible1() -> str:
                return "a1"

            @public
            @resource
            def accessible2() -> str:
                return "a2"

        root = evaluate(Namespace)
        assert "accessible1" in dir(root)
        assert "accessible2" in dir(root)
        assert getattr(root, "accessible1") == "a1"
        assert getattr(root, "accessible2") == "a2"


class TestParameter:
    """Test @extern decorator as syntactic sugar for empty patches (ported from V1)."""

    def test_parameter_with_keyword_argument_symbol(self) -> None:
        """Test that @extern registers a resource name and accepts injected values."""

        @scope
        class Config:
            @extern
            def database_url() -> str: ...

            @public
            @resource
            def connection_string(database_url: str) -> str:
                return f"Connected to: {database_url}"

        root = evaluate(Config)(database_url="postgresql://localhost/mydb")
        assert root.connection_string == "Connected to: postgresql://localhost/mydb"

    def test_parameter_with_dependencies(self) -> None:
        """Test that @extern can have its own dependencies."""

        @scope
        class Config:
            @resource
            def host() -> str:
                return "localhost"

            @extern
            def database_url(host: str) -> str:
                """This parameter depends on host but returns nothing useful."""
                return f"postgresql://{host}/db"  # Return value is ignored

            @public
            @resource
            def connection_string(database_url: str) -> str:
                return f"Connected to: {database_url}"

        root = evaluate(Config)(database_url="postgresql://prod-server/mydb")
        assert root.connection_string == "Connected to: postgresql://prod-server/mydb"

    def test_parameter_without_base_value_raises_error(self) -> None:
        """Test that accessing a @extern without providing a base value raises ValueError."""

        @scope
        class Config:
            @extern
            def database_url() -> str: ...

            @public
            @resource
            def connection_string(database_url: str) -> str:
                return f"Connected to: {database_url}"

        root = evaluate(Config)
        # V2 raises ValueError, not NotImplementedError like V1
        with pytest.raises(ValueError, match="requires instance scope"):
            _ = root.connection_string

    def test_parameter_equivalent_to_empty_patches(self) -> None:
        """Test that @extern is equivalent to @patch_many returning empty collection."""

        @scope
        class WithParameter:
            @public
            @extern
            def value() -> int: ...

        @scope
        class WithEmptyPatches:
            @public
            @patch_many
            def value() -> tuple[Callable[[int], int], ...]:
                return ()

        root_param = evaluate(WithParameter)(value=42)
        root_patches = evaluate(WithEmptyPatches)(value=42)

        assert root_param.value == 42
        assert root_patches.value == 42

    def test_parameter_multiple_injections(self) -> None:
        """Test that multiple @extern resources can be injected together."""

        @scope
        class Config:
            @extern
            def host() -> str: ...

            @extern
            def port() -> int: ...

            @public
            @resource
            def url(host: str, port: int) -> str:
                return f"http://{host}:{port}"

        root = evaluate(Config)(host="example.com", port=8080)
        assert root.url == "http://example.com:8080"

    def test_patch_with_identity_endo_equivalent_to_parameter(self) -> None:
        """Test that @patch with identity endo is equivalent to @extern."""

        @scope
        class WithParameter:
            @public
            @extern
            def value() -> int: ...

            @public
            @resource
            def doubled(value: int) -> int:
                return value * 2

        @scope
        class WithIdentityPatch:
            @public
            @patch
            def value() -> Callable[[int], int]:
                return lambda x: x

            @public
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

        @scope
        class WithIdentityPatch:
            @public
            @patch
            def config() -> Callable[[dict], dict]:
                return lambda x: x

        root = evaluate(WithIdentityPatch)
        # V2 raises ValueError, not NotImplementedError like V1
        with pytest.raises(ValueError, match="requires instance scope"):
            _ = root.config


class TestInstanceScopeV2Specific:
    """V2-specific instance scope tests."""

    def test_cannot_call_instance_again(self) -> None:
        """Cannot create instance from an instance scope."""

        @scope
        class Config:
            @extern
            def foo() -> str: ...

        root = evaluate(Config)
        instance = root(foo="bar")
        with pytest.raises(
            TypeError, match="'InstanceScope' object is not callable"
        ):
            instance(foo="baz")

    def test_extern_without_instance_raises_error(self) -> None:
        """Accessing @extern resource on static scope raises ValueError."""

        @scope
        class Config:
            @public
            @extern
            def foo() -> str: ...

        root = evaluate(Config)
        with pytest.raises(ValueError, match="requires instance scope"):
            _ = root.foo

    def test_extern_with_missing_kwarg_raises_error(self) -> None:
        """Accessing @extern resource without the kwarg raises ValueError."""

        @scope
        class Config:
            @extern
            def foo() -> str: ...

            @public
            @extern
            def bar() -> str: ...

        root = evaluate(Config)
        instance = root(foo="foo_value")  # bar not provided
        with pytest.raises(ValueError, match="requires kwargs"):
            _ = instance.bar

    def test_deeply_nested_instance_scope(self) -> None:
        """kwargs propagate through deeply nested scopes."""

        @scope
        class Root:
            @extern
            def value() -> int: ...

            @public
            @scope
            class Level1:
                @public
                @scope
                class Level2:
                    @public
                    @resource
                    def doubled(value: int) -> int:
                        return value * 2

        root = evaluate(Root)
        instance = root(value=21)
        assert instance.Level1.Level2.doubled == 42

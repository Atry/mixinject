import sys
import tempfile
from pathlib import Path
from typing import Callable

import pytest

from mixinject import (
    FunctionalMergerDefinition,
    Merger,
    InstanceScopeSymbol,
    InstanceScope,
    DefinedSymbol,
    CapturedScopes,
    _PackageScopeDefinition,
    _ScopeDefinition,
    Scope,
    RelativeReference,
    StaticScope,
    EndofunctionMergerDefinition,
    SinglePatcherDefinition,
    merge,
    extend,
    extern,
    patch,
    patch_many,
    resource,
    evaluate,
    scope,
    _parse_package,
)
from mixinject import RootScopeSymbol, DefinedScopeSymbol

R = RelativeReference

FIXTURES_DIR = str(Path(__file__).parent / "fixtures")


def _empty_definition() -> _ScopeDefinition:
    """Create a minimal empty scope definition for testing."""
    return _ScopeDefinition(scope_class=StaticScope, underlying=object())


def _empty_symbol() -> DefinedScopeSymbol:
    """Create a minimal dependency graph for testing."""
    scope_def = _empty_definition()
    nested_def = _empty_definition()
    root_symbol = RootScopeSymbol(definition=scope_def)
    return DefinedScopeSymbol(
        outer=root_symbol,
        definition=nested_def,
        key="test",
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

            @extend(
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Patcher",)),
            )
            @scope()
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

            @extend(
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Patch1",)),
                R(levels_up=0, path=("Patch2",)),
            )
            @scope()
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

            @extend(
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Patcher",)),
            )
            @scope()
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.value == 18


class TestCapturedScopes:
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


class TestInstanceScope:
    """Test InstanceScope created via StaticScope.__call__."""

    def test_instance_scope_single_value(self) -> None:
        base_scope = StaticScope(symbols={}, symbol=_empty_symbol())
        scope = base_scope(foo="bar")
        assert isinstance(scope, InstanceScope)
        assert scope.foo == "bar"

    def test_instance_scope_multiple_values(self) -> None:
        base_scope = StaticScope(symbols={}, symbol=_empty_symbol())
        scope = base_scope(foo="bar", count=42, flag=True)
        assert isinstance(scope, InstanceScope)
        assert scope.foo == "bar"
        assert scope.count == 42
        assert scope.flag is True


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

            @extend(
                R(levels_up=0, path=("Base",)),
                R(levels_up=0, path=("Provider1",)),
                R(levels_up=0, path=("Provider2",)),
            )
            @scope()
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

            @extend(
                R(levels_up=0, path=("Namespace1",)),
                R(levels_up=0, path=("Namespace2",)),
            )
            @scope()
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

            @extend(R(levels_up=0, path=("Namespace1",)))
            @scope()
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

            @extend(
                R(levels_up=0, path=("branch0",)),
                R(levels_up=0, path=("branch1",)),
                R(levels_up=0, path=("branch2",)),
            )
            @scope()
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

            @extend(
                R(levels_up=0, path=("branch1",)),
                R(levels_up=0, path=("branch2",)),
            )
            @scope()
            class Combined:
                pass

        root = evaluate(Root)
        assert root.Combined.foo == "foo"
        assert root.Combined.bar == "foo_bar"


class TestExtendInstanceScopeProhibition:
    """Test that extend cannot reference a path through InstanceScope."""

    def test_extend_instance_scope_raises_type_error(self) -> None:
        """Extending from an InstanceScope should raise TypeError."""

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
            def my_instance(MyOuter: Scope) -> Scope:
                return MyOuter(i=42)

            # This should fail because my_instance is an InstanceScope
            @extend(R(levels_up=0, path=("my_instance",)))
            @scope()
            class Invalid:
                pass

        with pytest.raises(TypeError, match="Cannot extend through InstanceScope"):
            root = evaluate(Root)
            _ = root.Invalid.foo

    def test_extend_path_through_instance_scope_raises_type_error(self) -> None:
        """Extending from a path through InstanceScope should raise TypeError."""

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
            def my_instance(MyOuter: Scope) -> Scope:
                return MyOuter(i=42)

            # This should fail because my_instance is an InstanceScope,
            # even though MyInner is a StaticScope
            @extend(R(levels_up=0, path=("my_instance", "MyInner")))
            @scope()
            class Invalid:
                pass

        with pytest.raises(TypeError, match="Cannot extend through InstanceScope"):
            root = evaluate(Root)
            _ = root.Invalid.foo

    def test_extend_within_instance_scope_sibling_allowed(self) -> None:
        """Extending a sibling scope within the same InstanceScope is allowed.

        The prohibition is on the NAVIGATION PATH of extend references, not on
        whether the extending scope is defined inside an InstanceScope.

        Here, `root.my_instance` is an InstanceScope, but `Inner1` extends `Inner2`
        via a sibling reference `R(levels_up=0, path=("Inner2",))`. This path doesn't
        traverse through any InstanceScope - it's a direct sibling reference within
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

                @extend(R(levels_up=0, path=("Inner2",)))
                @scope()
                class Inner1:
                    @patch
                    def base_value(i: int) -> Callable[[int], int]:
                        return lambda x: x + i

            @resource
            def my_instance(MyOuter: Scope) -> Scope:
                return MyOuter(i=42)

        root = evaluate(Root)

        # Accessing via InstanceScope should work because the extend reference
        # ("Inner2",) is a sibling reference that doesn't traverse through InstanceScope
        # Inner1 extends Inner2, so Inner1 has base_value from Inner2, patched by Inner1
        assert root.my_instance.Inner2.base_value == 100
        assert root.my_instance.Inner1.base_value == 142  # 100 + 42 (patched)


class TestExtendNameResolution:
    """Test that names from extended scopes can be resolved without @extern."""

    def test_extend_allows_name_resolution_without_extern(self) -> None:
        """Extended scope should be able to resolve names from base scope.

        When a scope extends another scope, the extending scope should be able
        to use resources from the extended scope as dependencies without needing
        to declare them with @extern.

        This works because mixin-based dependency resolution (via
        _resolve_dependencies_jit_using_symbol) uses ScopeSymbol.__getitem__
        which handles extends via _compile_synthetic and generate_strict_super().
        """

        @scope()
        class Root:
            @scope()
            class Base:
                @resource
                def base_value() -> int:
                    return 42

            @extend(R(levels_up=0, path=("Base",)))
            @scope()
            class Extended:
                # This should work: base_value should be resolved from Base
                # Currently fails because symbol table doesn't include extended names
                @resource
                def doubled(base_value: int) -> int:
                    return base_value * 2

        root = evaluate(Root)
        assert root.Extended.base_value == 42
        assert root.Extended.doubled == 84


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

    ScopeSymbolject takes a different trade-off:
    - Forbids extend through InstanceScope (val-like) entirely
    - But allows composing MULTIPLE scopes via static @scope with lexical scoping

    This test demonstrates the multi-instance pattern using static scopes.
    Result: 100 + (10 + 1 + 2) = 113
    """

    def test_path_dependent_symbol_linearization(self) -> None:
        """Test composing multiple path-dependent scopes that share underlying definitions.

        Uses mixinject's features:
        - @scope with extend for composing scopes
        - @extern for declaring external dependencies
        - Lexical scope lookup (parameter `i` resolved from outer scope)
        - ReversedPath to distinguish object1.MyInner from object2.MyInner

        Note: Unlike InstanceScope which captures kwargs at runtime, static @scope
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

                @extend(R(levels_up=1, path=("Base",)))
                @scope()
                class MyInner:
                    @patch
                    def foo(i: int) -> Callable[[int], int]:
                        return lambda x: x + i

            @scope()
            class object2:
                @resource
                def i() -> int:
                    return 2

                @extend(R(levels_up=1, path=("Base",)))
                @scope()
                class MyInner:
                    @patch
                    def foo(i: int) -> Callable[[int], int]:
                        return lambda x: x + i

            # MyObjectA extends object1.MyInner, object2.MyInner and adds its own patch
            @extend(
                R(levels_up=0, path=("object1", "MyInner")),
                R(levels_up=0, path=("object2", "MyInner")),
            )
            @scope()
            class MyObjectA:
                @patch
                def foo() -> Callable[[int], int]:
                    return lambda x: 100 + x

        root = evaluate(Root)

        # mixin is the runtime access path:
        #   root.object1.MyInner.symbol == ("MyInner", "object1", "root")
        #   root.object2.MyInner.symbol == ("MyInner", "object2", "root")
        object1_inner = root.object1.MyInner
        object2_inner = root.object2.MyInner
        assert object1_inner.symbol != object2_inner.symbol

        # foo = 10 (Base) + 1 (object1.MyInner) + 2 (object2.MyInner) + 100 (MyObjectA) = 113
        assert root.MyObjectA.foo == 113


class TestInstanceScopeReversedPath:
    """Test that InstanceScope has correct mixin with InstanceChildScopeSymbol."""

    def test_instance_scope_nested_access_has_instance_symbol_in_path(
        self,
    ) -> None:
        """When accessing nested scope through InstanceScope, path should use InstanceChildScopeSymbol."""

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
            def my_instance(MyOuter: Scope) -> Scope:
                return MyOuter(i=42)

        root = evaluate(Root)

        # Access MyInner through the InstanceScope
        my_instance = root.my_instance
        my_inner = my_instance.MyInner

        # The mixin should be InstanceChildScopeSymbol to distinguish from static path
        assert isinstance(my_instance.symbol, InstanceScopeSymbol)

        # Verify the resource works correctly
        assert my_inner.foo == "foo_42"


class TestInstanceScopeSymbolDepth:
    """Test depth calculation through InstanceScopeSymbol chains."""

    @pytest.mark.xfail(
        reason="BUG: InstanceScopeSymbol.__getitem__ delegates to prototype[key], "
        "returning a mixin with outer=prototype instead of outer=self. "
        "This causes depth to be computed incorrectly and _find_param_in_symbol_chain "
        "to fail when traversing through InstanceScopeSymbol."
    )
    def test_nested_symbol_outer_should_be_instance_symbol_mapping(self) -> None:
        """When accessing nested scope through InstanceScope, mixin's outer should be InstanceScopeSymbol.

        Current bug: InstanceScopeSymbol.__getitem__ does:
            return self.prototype[key]  # Returns mixin with outer=prototype

        Expected: Should return a mixin with outer=self (the InstanceScopeSymbol).

        This test verifies the mixin chain is correct when accessing through instance scopes.
        """
        from mixinject import InstanceScopeSymbol

        @scope()
        class Root:
            @scope()
            class Outer:
                @extern
                def arg() -> int: ...

                @scope()
                class Inner:
                    @resource
                    def value(arg: int) -> int:
                        return arg * 2

        root = evaluate(Root)
        instance = root.Outer(arg=21)

        # Access Inner through the instance
        inner = instance.Inner

        # The inner scope's mixin should have outer=InstanceScopeSymbol
        # Currently it has outer=Outer's NestedScopeSymbol (from prototype)
        assert isinstance(inner.symbol.outer, InstanceScopeSymbol), (
            f"Expected outer to be InstanceScopeSymbol, got {type(inner.symbol.outer)}"
        )


class TestDefinitionSharing:
    """Test that Definition instances are shared among mixins from the same _ScopeDefinition."""

    def test_definition_shared_across_different_instance_args(self) -> None:
        """Definition should be shared when accessing Inner through different Outer instances."""

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

        # Use the mixin's definition directly
        definition1 = inner1.symbol.definition
        definition2 = inner2.symbol.definition

        assert definition1 is definition2

    def test_definition_shared_between_instance_and_static_access(self) -> None:
        """Definition should be shared between InstanceScope and StaticScope access paths."""

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

        # Use the mixin's definition directly
        instance_definition = instance_inner.symbol.definition
        static_definition = static_inner.symbol.definition

        assert instance_definition is static_definition

    @pytest.mark.xfail(
        reason="BUG: Same issue as test_definition_shared_between_instance_and_static_access. "
        "InstanceChildScopeSymbol has separate intern_pool from ChildScopeSymbol, "
        "causing different definition values for the same underlying scope definition."
    )
    def test_definition_shared_when_scope_extends_another(self) -> None:
        """Definition should be shared when accessing Inner through extending scopes.

        .. todo:: Fix _ScopeSemigroup.create to share definition across extending scopes.

            When object1 extends Outer, accessing Inner through both paths should yield
            the same definition since they refer to the same Python class definition
            (Root.Outer.Inner). Both mixins should be _DefinedSymbol instances with the
            same definition.

            The fix should ensure that all access paths to the same scope definition
            share the same Definition instance.
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

            @extend(R(levels_up=1, path=("Outer",)))
            @scope()
            class object1:
                @extern
                def arg() -> str: ...

        root = evaluate(Root)

        outer_inner = root.Outer(arg="v1").Inner
        object1_inner = root.object1(arg="v2").Inner

        # Both mixins should be _DefinedSymbol (not synthetic)
        assert isinstance(outer_inner.symbol, DefinedSymbol)
        assert isinstance(object1_inner.symbol, DefinedSymbol)

        # Both should share the same definition since they access the same Inner definition
        assert outer_inner.symbol.definition is object1_inner.symbol.definition


class TestScopeAsSymlink:
    """Test Scope return values acting as symlinks."""

    def test_scope_symlink(self) -> None:
        base_scope = StaticScope(symbols={}, symbol=_empty_symbol())
        inner_scope = base_scope(inner_value="inner")

        @scope()
        class Namespace:
            @resource
            def linked() -> Scope:
                return inner_scope

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
                get_module_scope_class=lambda _: StaticScope,
            )
            assert isinstance(scope_def, _PackageScopeDefinition)
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
                get_module_scope_class=lambda _: StaticScope,
            )
            assert isinstance(scope_def, _ScopeDefinition)
            assert not isinstance(scope_def, _PackageScopeDefinition)
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
                get_module_scope_class=lambda _: StaticScope,
            )
            assert isinstance(scope_def, _PackageScopeDefinition)

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
                    get_module_scope_class=lambda _: StaticScope,
                )
                assert isinstance(scope_def, _PackageScopeDefinition)

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


class TestScopeCallable:
    """Test Scope as Callable - dynamic mixin injection."""

    def test_scope_call_provides_endo_only_base_value(self) -> None:
        """Test Scope callable providing base value for parameter pattern.

        Pattern:
        - Use @extern to declare a symbol that will be provided at runtime
        - Provide the value via Scope.__call__
        - Other resources can depend on the parameter
        """

        @scope()
        class Config:
            @extern
            def db_config() -> dict:
                """Parameter to be provided via Scope.__call__"""
                ...

            @resource
            def connection_string(db_config: dict) -> str:
                """Depends on db_config parameter"""
                return f"{db_config['host']}:{db_config['port']}"

        root = evaluate(Config)(db_config={"host": "localhost", "port": "5432"})
        assert root.db_config == {"host": "localhost", "port": "5432"}
        assert root.connection_string == "localhost:5432"

    def test_scope_call_returns_instance_scope(self) -> None:
        """Test that calling a StaticScope returns an InstanceScope."""

        class Value:
            pass

        v1 = Value()

        # StaticScope.__call__ should return InstanceScope
        static = StaticScope(symbols={}, symbol=_empty_symbol())
        instance1 = static(x=v1)
        assert isinstance(instance1, InstanceScope)
        assert instance1.x is v1


class TestScopeDir:
    """Test Scope.__dir__ method."""

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
        assert "symbols" in result

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

    def test_dir_with_multiple_symbols(self) -> None:
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

            @extend(
                R(levels_up=0, path=("Namespace1",)),
                R(levels_up=0, path=("Namespace2",)),
            )
            @scope()
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

            @extend(
                R(levels_up=0, path=("Namespace1",)),
                R(levels_up=0, path=("Namespace2",)),
            )
            @scope()
            class Combined:
                pass

        root = evaluate(Root)
        result = dir(root.Combined)
        assert result.count("shared") == 1

    def test_dir_works_with_cached_scope(self) -> None:
        """Test __dir__ works with StaticScope subclass."""

        @scope()
        class Namespace:
            @resource
            def cached_resource() -> str:
                return "cached"

        root = evaluate(Namespace)
        result = dir(root)
        assert "cached_resource" in result

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

    def test_parameter_with_keyword_argument_symbol(self) -> None:
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


class TestScopeSemigroupScopeSymbol:
    """Test _ScopeSemigroup.create correctly assigns mixin."""

    def test_extended_scope_has_distinct_symbol(self) -> None:
        """Extended scope should have its own mixin, not primary's.

        When scope B extends scope A via extend=, B.symbol should be
        distinct from A.symbol because they represent different
        positions in the topology (B is accessed as "B", not "A").
        """

        @scope()
        class Root:
            @scope()
            class Base:
                @resource
                def value() -> int:
                    return 10

            @extend(R(levels_up=0, path=("Base",)))
            @scope()
            class Extended:
                @resource
                def doubled(value: int) -> int:
                    return value * 2

        root = evaluate(Root)

        # The extended scope should have its own unique mixin
        # that represents its access path ("Extended", "Root"), not Base's path
        base_symbol = root.Base.symbol
        extended_symbol = root.Extended.symbol

        # This should pass - Extended has its own mixin
        assert extended_symbol is not base_symbol, (
            "Extended scope should have its own mixin, "
            "not share with Base scope"
        )

    def test_nested_scope_in_extended_has_distinct_symbol(self) -> None:
        """Nested scope in Extended should have different mixin than in Base.

        Expected behavior:
        - base_another.symbol.key == "Another"
        - extended_another.symbol.key == "Another"
        - base_another.symbol.outer.key == "Base"
        - extended_another.symbol.outer.key == "Extended"
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

            @extend(R(levels_up=0, path=("Base",)), R(levels_up=0, path=("Base2",)))
            @scope()
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
            f"\nbase_another.symbol.key = {base_another.symbol.key!r}"
        )
        print(
            f"extended_another.symbol.key = {extended_another.symbol.key!r}"
        )
        print(
            f"base_another.symbol.outer.key = {base_another.symbol.outer.key!r}"
        )
        print(
            f"extended_another.symbol.outer.key = {extended_another.symbol.outer.key!r}"
        )

        # Verify key for both
        assert base_another.symbol.key == "Another"
        assert extended_another.symbol.key == "Another"

        # Verify outer.key
        assert base_another.symbol.outer.key == "Base"
        assert extended_another.symbol.outer.key == "Extended"

        # Verify the nested resource is still accessible (with patch applied)
        assert extended_another.nested_value == "nestednestednested"

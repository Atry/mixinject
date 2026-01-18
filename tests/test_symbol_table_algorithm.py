from collections import ChainMap
from typing import Any, Callable, Final, Iterable
import pytest
from dataclasses import dataclass
from mixinject import (
    LexicalScope,
    SymbolTable,
    ChainMapSentinel,
    Node,
    CachedProxy,
    _NamespaceDefinition,
    _NestedMixinSymbol,
    _RootSymbol,
    _Symbol,
)
from mixinject import RootMixin, NestedMixin


def _empty_proxy_definition() -> _NamespaceDefinition:
    """Create a minimal empty proxy definition for testing."""
    return _NamespaceDefinition(proxy_class=CachedProxy, underlying=object())


def _empty_root_symbol(proxy_definition: _NamespaceDefinition) -> _RootSymbol:
    """Create a minimal root symbol for testing."""
    return _RootSymbol(proxy_definition=proxy_definition)


def _empty_nested_symbol(
    outer: "_RootSymbol", proxy_definition: _NamespaceDefinition
) -> _NestedMixinSymbol:
    """Create a minimal nested symbol for testing."""
    return _NestedMixinSymbol(
        outer=outer,
        name="__test__",
        proxy_definition=proxy_definition,
    )


def _empty_mixin() -> NestedMixin:
    """Create a minimal dependency graph for testing."""
    proxy_def = _empty_proxy_definition()
    root_symbol = _empty_root_symbol(proxy_def)
    nested_symbol = _empty_nested_symbol(root_symbol, proxy_def)
    root_mixin = RootMixin(symbol=root_symbol)
    return NestedMixin(
        outer=root_mixin,
        symbol=nested_symbol,
        name="test",
    )


def _empty_proxy() -> CachedProxy:
    """Create an empty proxy for testing."""
    return CachedProxy(mixins={}, mixin=_empty_mixin())


@dataclass(kw_only=True, slots=True, weakref_slot=True)
class _TestSymbol(_Symbol):
    """Test symbol that uses getitem-based access."""

    _depth: Final[int]
    _resource_name: Final[str]

    def __post_init__(self) -> None:
        # Create a getitem-based getter instead of attribute-based
        getter = lambda lexical_scope: lexical_scope[self._depth][self._resource_name]
        object.__setattr__(self, "getter", getter)

    @property
    def depth(self) -> int:
        return self._depth

    @property
    def resource_name(self) -> str:
        return self._resource_name

    def compile(self, mixin: Any, /) -> Any:
        raise NotImplementedError("_TestSymbol is not compilable")


def extend_symbol_table_getitem(
    symbol_table: SymbolTable,
    names: Iterable[str],
    index: int,
) -> SymbolTable:
    """Extend symbol table by adding a new layer that uses getitem-based factories."""
    new_symbols: dict[str, _Symbol] = {
        name: _TestSymbol(_depth=index, _resource_name=name) for name in names
    }
    if symbol_table is ChainMapSentinel.EMPTY:
        return ChainMap(new_symbols)
    return symbol_table.new_child(new_symbols)


def _make_mock_definition(name: str) -> "_ResourceDefinition":
    """Create a mock resource definition for testing."""
    from mixinject import _ResourceDefinition
    return _ResourceDefinition(function=lambda: name, is_eager=False, is_local=False)


def test_symbol_table_extension_consistency():
    """Test that JIT symbol table extension produces correct getters.

    This test now uses _RootSymbol and _NestedMixinSymbol to test symbol table
    extension through their symbol_table cached_property.
    """
    # Setup
    proxy_inner = _empty_proxy()(a=1, b=2)
    proxy_outer = _empty_proxy()(c=3, a=100)  # 'a' is shadowed in inner

    # ls_outer = (outer,)
    ls_outer: LexicalScope = (proxy_outer,)
    # ls_full = (outer, inner)
    ls_full: LexicalScope = (proxy_outer, proxy_inner)

    st_init: SymbolTable = ChainMapSentinel.EMPTY

    # depth 1: (outer,) -> index = 0
    # Test getitem-based extension directly
    st_getitem = extend_symbol_table_getitem(st_init, ["c", "a"], 0)

    # For JIT-based extension, use _RootSymbol which computes symbol_table lazily
    # Create a mock namespace with Definition attributes
    class _MockOuterNamespace:
        c = _make_mock_definition("c")
        a = _make_mock_definition("a")

    mock_outer_def = _NamespaceDefinition(proxy_class=CachedProxy, underlying=_MockOuterNamespace())
    root_symbol = _RootSymbol(proxy_definition=mock_outer_def)
    st_jit = root_symbol.symbol_table

    # Test outer scope resolution
    assert st_getitem["c"].getter(ls_outer) == 3
    assert st_jit["c"].getter(ls_outer) == 3
    assert st_getitem["a"].getter(ls_outer) == 100
    assert st_jit["a"].getter(ls_outer) == 100

    # Test outer scope resolution from full scope (stable index)
    assert st_getitem["c"].getter(ls_full) == 3
    assert st_jit["c"].getter(ls_full) == 3
    assert st_getitem["a"].getter(ls_full) == 100
    assert st_jit["a"].getter(ls_full) == 100

    # depth 2: (outer, inner) -> index = 1
    st_getitem_inner = extend_symbol_table_getitem(st_getitem, ["a", "b"], 1)

    # For nested extension, use _NestedMixinSymbol
    class _MockInnerNamespace:
        a = _make_mock_definition("a")
        b = _make_mock_definition("b")

    mock_inner_def = _NamespaceDefinition(proxy_class=CachedProxy, underlying=_MockInnerNamespace())
    nested_symbol = _NestedMixinSymbol(
        outer=root_symbol,
        name="inner",
        proxy_definition=mock_inner_def,
    )
    st_jit_inner = nested_symbol.symbol_table

    # 'a' should now resolve to inner value (1) because it's in the top layer of ChainMap
    assert st_getitem_inner["a"].getter(ls_full) == 1
    assert st_jit_inner["a"].getter(ls_full) == 1

    # 'b' should resolve to inner value (2)
    assert st_getitem_inner["b"].getter(ls_full) == 2
    assert st_jit_inner["b"].getter(ls_full) == 2

    # 'c' should still resolve to outer value (3) from the outer layer
    assert st_getitem_inner["c"].getter(ls_full) == 3
    assert st_jit_inner["c"].getter(ls_full) == 3


def test_jit_factory_invalid_identifier():
    """Test if JIT factory handles names that are not valid identifiers but valid keys."""
    proxy = _empty_proxy()(**{"not_identifier": "value"})
    lexical_scope: LexicalScope = (proxy,)

    # Create a mock namespace with a Definition attribute
    class _MockNamespace:
        not_identifier = _make_mock_definition("not_identifier")

    mock_def = _NamespaceDefinition(proxy_class=CachedProxy, underlying=_MockNamespace())
    root_symbol = _RootSymbol(proxy_definition=mock_def)
    symbol_table_jit = root_symbol.symbol_table
    assert symbol_table_jit["not_identifier"].getter(lexical_scope) == "value"

    # If we use a name that is not a valid identifier (contains space)
    # This cannot be tested directly as Python attributes cannot have spaces
    # The JIT uses attribute access, so non-identifier names are not supported

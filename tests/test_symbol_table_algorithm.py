from collections import ChainMap
from typing import Callable, Final, Iterable
import pytest
from dataclasses import dataclass
from mixinject import (
    LexicalScope,
    SymbolTable,
    ChainMapSentinel,
    Node,
    CachedProxy,
    _extend_symbol_table_jit,
    _NamespaceDefinition,
    _MixinSymbol,
    _Symbol,
)
from mixinject import RootMixin, NestedMixin


def _empty_proxy_definition() -> _NamespaceDefinition:
    """Create a minimal empty proxy definition for testing."""
    return _NamespaceDefinition(proxy_class=CachedProxy, underlying=object())


def _empty_symbol(proxy_definition: _NamespaceDefinition) -> _MixinSymbol:
    """Create a minimal symbol for testing."""
    return _MixinSymbol(
        name="__test__",
        proxy_definition=proxy_definition,
        symbol_table=ChainMapSentinel.EMPTY,
    )


def _empty_mixin() -> NestedMixin:
    """Create a minimal dependency graph for testing."""
    proxy_def = _empty_proxy_definition()
    symbol = _empty_symbol(proxy_def)
    return NestedMixin(
        outer=RootMixin(symbol=symbol),
        symbol=symbol,
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


def test_symbol_table_extension_consistency():
    # Setup
    proxy_inner = _empty_proxy()(a=1, b=2)
    proxy_outer = _empty_proxy()(c=3, a=100)  # 'a' is shadowed in inner

    # ls_outer = (outer,)
    ls_outer: LexicalScope = (proxy_outer,)
    # ls_full = (outer, inner)
    ls_full: LexicalScope = (proxy_outer, proxy_inner)

    st_init: SymbolTable = ChainMapSentinel.EMPTY

    # depth 1: (outer,) -> index = 0
    st_getitem = extend_symbol_table_getitem(st_init, ["c", "a"], 0)
    st_jit = _extend_symbol_table_jit(st_init, ["c", "a"])

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
    st_jit_inner = _extend_symbol_table_jit(st_jit, ["a", "b"])

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
    # Test if JIT factory handles names that are not valid identifiers but valid keys
    proxy = _empty_proxy()(**{"not_identifier": "value"})
    lexical_scope: LexicalScope = (proxy,)

    symbol_table_jit = _extend_symbol_table_jit(ChainMapSentinel.EMPTY, ["not_identifier"])
    assert symbol_table_jit["not_identifier"].getter(lexical_scope) == "value"

    # If we use a name that is not a valid identifier
    invalid_name = "not an identifier"
    proxy_invalid = _empty_proxy()(**{invalid_name: "value"})
    lexical_scope_invalid: LexicalScope = (proxy_invalid,)

    try:
        symbol_table_jit_invalid = _extend_symbol_table_jit(
            ChainMapSentinel.EMPTY, [invalid_name]
        )
    except (SyntaxError, ValueError, TypeError):
        # Expected if JIT doesn't support non-identifiers
        return

    # If it compiled, it should work (though .attr syntax doesn't support it in source,
    # AST can represent it and it usually works if the underlying object supports it)
    assert symbol_table_jit_invalid[invalid_name].getter(lexical_scope_invalid) == "value"

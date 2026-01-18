from collections import ChainMap
from typing import Callable, Iterable
import pytest
from mixinject import (
    LexicalScope,
    SymbolTable,
    SymbolTableSentinel,
    Node,
    CachedProxy,
    _extend_symbol_table_jit,
    _NamespaceDefinition,
    _JitCache,
)
from mixinject import RootDependencyGraph, StaticChildDependencyGraph


def _empty_proxy_definition() -> _NamespaceDefinition:
    """Create a minimal empty proxy definition for testing."""
    return _NamespaceDefinition(proxy_class=CachedProxy, underlying=object())


def _empty_jit_cache(proxy_definition: _NamespaceDefinition) -> _JitCache:
    """Create a minimal JIT cache for testing."""
    return _JitCache(
        proxy_definition=proxy_definition,
        symbol_table=SymbolTableSentinel.ROOT,
    )


def _empty_dependency_graph() -> StaticChildDependencyGraph[str]:
    """Create a minimal dependency graph for testing."""
    proxy_def = _empty_proxy_definition()
    jit_cache = _empty_jit_cache(proxy_def)
    return StaticChildDependencyGraph(
        proxy_definition=proxy_def,
        outer=RootDependencyGraph(proxy_definition=proxy_def, jit_cache=jit_cache),
        jit_cache=jit_cache,
        resource_name="test",
    )


def _empty_proxy() -> CachedProxy:
    """Create an empty proxy for testing."""
    return CachedProxy(mixins={}, dependency_graph=_empty_dependency_graph())

def _make_getitem_factory(
    name: str, index: int
) -> Callable[[LexicalScope], "Node"]:
    """Create a factory that retrieves a resource from lexical scope using getitem."""
    return lambda ls: ls[index][name]


def extend_symbol_table_getitem(
    symbol_table: SymbolTable,
    names: Iterable[str],
    index: int,
) -> SymbolTable:
    """Extend symbol table by adding a new layer that uses getitem-based factories."""
    if symbol_table is SymbolTableSentinel.ROOT:
        return ChainMap({name: _make_getitem_factory(name, index) for name in names})
    return symbol_table.new_child(
        {name: _make_getitem_factory(name, index) for name in names}
    )

def test_symbol_table_extension_consistency():
    # Setup
    proxy_inner = _empty_proxy()(a=1, b=2)
    proxy_outer = _empty_proxy()(c=3, a=100) # 'a' is shadowed in inner
    
    # ls_outer = (outer,)
    ls_outer: LexicalScope = (proxy_outer,)
    # ls_full = (outer, inner)
    ls_full: LexicalScope = (proxy_outer, proxy_inner)
    
    st_init: SymbolTable = SymbolTableSentinel.ROOT

    # depth 1: (outer,) -> index = 0
    st_getitem = extend_symbol_table_getitem(st_init, ["c", "a"], 0)
    st_jit = _extend_symbol_table_jit(st_init, ["c", "a"])
    
    # Test outer scope resolution
    assert st_getitem["c"](ls_outer) == 3
    assert st_jit["c"](ls_outer) == 3
    assert st_getitem["a"](ls_outer) == 100
    assert st_jit["a"](ls_outer) == 100
    
    # Test outer scope resolution from full scope (stable index)
    assert st_getitem["c"](ls_full) == 3
    assert st_jit["c"](ls_full) == 3
    assert st_getitem["a"](ls_full) == 100
    assert st_jit["a"](ls_full) == 100
    
    # depth 2: (outer, inner) -> index = 1
    st_getitem_inner = extend_symbol_table_getitem(st_getitem, ["a", "b"], 1)
    st_jit_inner = _extend_symbol_table_jit(st_jit, ["a", "b"])
    
    # 'a' should now resolve to inner value (1) because it's in the top layer of ChainMap
    assert st_getitem_inner["a"](ls_full) == 1
    assert st_jit_inner["a"](ls_full) == 1
    
    # 'b' should resolve to inner value (2)
    assert st_getitem_inner["b"](ls_full) == 2
    assert st_jit_inner["b"](ls_full) == 2
    
    # 'c' should still resolve to outer value (3) from the outer layer
    assert st_getitem_inner["c"](ls_full) == 3
    assert st_jit_inner["c"](ls_full) == 3

def test_jit_factory_invalid_identifier():
    # Test if JIT factory handles names that are not valid identifiers but valid keys
    proxy = _empty_proxy()(**{"not_identifier": "value"})
    lexical_scope: LexicalScope = (proxy,)

    symbol_table_jit = _extend_symbol_table_jit(SymbolTableSentinel.ROOT, ["not_identifier"])
    assert symbol_table_jit["not_identifier"](lexical_scope) == "value"

    # If we use a name that is not a valid identifier
    invalid_name = "not an identifier"
    proxy_invalid = _empty_proxy()(**{invalid_name: "value"})
    lexical_scope_invalid: LexicalScope = (proxy_invalid,)

    try:
        symbol_table_jit_invalid = _extend_symbol_table_jit(SymbolTableSentinel.ROOT, [invalid_name])
    except (SyntaxError, ValueError, TypeError):
        # Expected if JIT doesn't support non-identifiers
        return

    # If it compiled, it should work (though .attr syntax doesn't support it in source,
    # AST can represent it and it usually works if the underlying object supports it)
    assert symbol_table_jit_invalid[invalid_name](lexical_scope_invalid) == "value"
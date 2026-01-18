from collections import ChainMap
from dataclasses import dataclass
from inspect import signature
from typing import Any, Callable, Final, Iterator, ParamSpec, TypeVar
from unittest.mock import Mock

import pytest
from mixinject import (
    LexicalScope,
    Proxy,
    SymbolTable,
    _resolve_dependencies_jit,
    _Symbol,
)

P = ParamSpec("P")
T = TypeVar("T")


@dataclass(kw_only=True, slots=True, weakref_slot=True)
class _MockSymbol(_Symbol):
    """Mock symbol for testing that wraps a getter function."""

    _getter_func: Final[Callable[[LexicalScope], Any]]
    _depth: Final[int] = 0
    _resource_name: Final[str] = ""

    def __post_init__(self) -> None:
        # Override the getter with our custom function instead of using the parent's JIT getter
        object.__setattr__(self, "getter", self._getter_func)

    @property
    def depth(self) -> int:
        return self._depth

    @property
    def resource_name(self) -> str:
        return self._resource_name


def _make_mock_symbol_table(mapping: dict[str, Callable[[LexicalScope], Any]]) -> SymbolTable:
    """Create a symbol table from a dict of name -> getter function."""
    symbols: dict[str, _Symbol] = {
        name: _MockSymbol(_getter_func=getter) for name, getter in mapping.items()
    }
    return ChainMap(symbols)


def _resolve_dependencies_kwargs(
    symbol_table: SymbolTable,
    function: Callable[P, T],
    name: str,
) -> Callable[[LexicalScope], T]:
    """
    Resolve dependencies for a function using standard keyword arguments.
    (Testing version)
    """
    sig = signature(function)
    params = tuple(sig.parameters.values())

    has_proxy = False
    if params:
        p0 = params[0]
        if (p0.kind == p0.POSITIONAL_ONLY) or (
            p0.kind == p0.POSITIONAL_OR_KEYWORD and p0.name not in symbol_table
        ):
            has_proxy = True
            kw_params = params[1:]
        else:
            kw_params = params
    else:
        kw_params = []

    def resolved_function(lexical_scope: LexicalScope) -> T:
        kwargs = {
            param.name: (
                symbol_table.parents[param.name].getter(lexical_scope)
                if param.name == name
                else symbol_table[param.name].getter(lexical_scope)
            )
            for param in kw_params
        }

        if has_proxy:
            return function(lexical_scope[0], **kwargs)  # type: ignore
        else:
            return function(**kwargs)  # type: ignore

    return resolved_function


def test_resolve_dependencies_consistency():
    lexical_scope: LexicalScope = ()

    mock_proxy = Mock(spec=Proxy)

    # Mock symbol table
    symbol_table = _make_mock_symbol_table(
        {
            "a": lambda ls: 1,
            "b": lambda ls: 2,
            "c": lambda ls: 3,
        }
    )

    test_cases: list[Callable[..., Any]] = [
        # No arguments
        lambda: "no args",
        # Only proxy (positional only)
        lambda p, /: f"proxy only: {p}",
        # Only proxy (name not in symbol table)
        lambda proxy: f"proxy only: {proxy}",
        # Mixed proxy and dependencies
        lambda p, /, a, b: f"p={p}, a={a}, b={b}",
        lambda proxy, a, b: f"proxy={proxy}, a={a}, b={b}",
        # Only dependencies
        lambda a, b: f"a={a}, b={b}",
        # Dependency named as proxy but it IS in symbol table
        lambda a: f"a={a}",
    ]

    for func in test_cases:
        resolved_kwargs = _resolve_dependencies_kwargs(symbol_table, func, "dummy")
        resolved_jit = _resolve_dependencies_jit(symbol_table, func, "dummy")

        result_kwargs = resolved_kwargs((mock_proxy, *lexical_scope))
        result_jit = resolved_jit((mock_proxy, *lexical_scope))

        assert result_kwargs == result_jit, f"Consistency failed for {func}"
        if "no args" in str(result_kwargs):
            assert result_kwargs == "no args"
        elif "proxy only" in str(result_kwargs):
            # Check if mock_proxy or its string representation is in result
            assert str(mock_proxy) in str(result_kwargs)


def test_resolve_dependencies_complex_signatures():
    lexical_scope: LexicalScope = ()

    mock_proxy = Mock(spec=Proxy)
    symbol_table = _make_mock_symbol_table({"a": lambda ls: 10, "b": lambda ls: 20})

    # Positional only argument named 'a' which is in symbol table
    # Since it is positional only, it should be treated as proxy.
    def func1(a, /, b):
        return (a, b)

    res_kwargs = _resolve_dependencies_kwargs(symbol_table, func1, "dummy")
    res_jit = _resolve_dependencies_jit(symbol_table, func1, "dummy")

    assert res_kwargs((mock_proxy, *lexical_scope)) == (mock_proxy, 20)
    assert res_jit((mock_proxy, *lexical_scope)) == (mock_proxy, 20)

    # Positional or keyword argument named 'a' which is in symbol table
    # It should NOT be treated as proxy.
    def func2(a, b):
        return (a, b)

    res_kwargs = _resolve_dependencies_kwargs(symbol_table, func2, "dummy")
    res_jit = _resolve_dependencies_jit(symbol_table, func2, "dummy")

    assert res_kwargs((mock_proxy, *lexical_scope)) == (10, 20)
    assert res_jit((mock_proxy, *lexical_scope)) == (10, 20)


def test_resolve_dependencies_same_name():
    lexical_scope: LexicalScope = ()
    mock_proxy = Mock(spec=Proxy)

    # Layered symbol table
    inner_symbols: dict[str, _Symbol] = {
        "a": _MockSymbol(_getter_func=lambda ls: "inner_a")
    }
    outer_symbols: dict[str, _Symbol] = {
        "a": _MockSymbol(_getter_func=lambda ls: "outer_a")
    }
    symbol_table: SymbolTable = ChainMap(inner_symbols, outer_symbols)

    # When param name is 'a', and name is also 'a'
    # It should look up 'a' in symbol_table.parents (outer_table)
    def func(a):
        return a

    # Test kwargs implementation
    res_kwargs = _resolve_dependencies_kwargs(symbol_table, func, "a")
    assert res_kwargs((mock_proxy, *lexical_scope)) == "outer_a"

    # Test jit implementation
    res_jit = _resolve_dependencies_jit(symbol_table, func, "a")
    assert res_jit((mock_proxy, *lexical_scope)) == "outer_a"

    # When name is different, it should use inner_table
    res_kwargs_diff = _resolve_dependencies_kwargs(symbol_table, func, "other")
    assert res_kwargs_diff((mock_proxy, *lexical_scope)) == "inner_a"

    res_jit_diff = _resolve_dependencies_jit(symbol_table, func, "other")
    assert res_jit_diff((mock_proxy, *lexical_scope)) == "inner_a"

"""Module B in namespace package with internal dependencies."""

from mixinject import resource


@resource
def base() -> str:
    return "base"


@resource
def derived(base: str) -> str:
    return f"{base}_derived"

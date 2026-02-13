"""Module B in namespace package with internal dependencies."""

from ol import public, resource


@public
@resource
def base() -> str:
    return "base"


@public
@resource
def derived(base: str) -> str:
    return f"{base}_derived"

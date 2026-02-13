"""Module A in namespace package."""

from ol import public, resource


@public
@resource
def value_a() -> str:
    return "a"

"""Module A in namespace package."""

from overlay.language import public, resource


@public
@resource
def value_a() -> str:
    return "a"

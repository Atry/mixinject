"""Module A in namespace package."""

from mixinject import resource


@resource
def value_a() -> str:
    return "a"

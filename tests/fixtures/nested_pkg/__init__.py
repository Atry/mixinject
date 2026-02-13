"""Nested package for testing lazy import depth."""
from ol import public, resource


@public
@resource
def root_value() -> str:
    return "from_root"

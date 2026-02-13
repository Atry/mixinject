"""Nested package for testing lazy import depth."""
from overlay.language import public, resource


@public
@resource
def root_value() -> str:
    return "from_root"

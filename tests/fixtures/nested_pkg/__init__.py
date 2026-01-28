"""Nested package for testing lazy import depth."""
from mixinject import resource


@resource
def root_value() -> str:
    return "from_root"

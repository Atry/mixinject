"""A regular module (not a package) for testing."""

from mixinject import resource


@resource
def value() -> int:
    return 123

"""A regular module (not a package) for testing."""

from ol import resource


@resource
def value() -> int:
    return 123

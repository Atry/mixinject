"""A regular module (not a package) for testing."""

from overlay.language import resource


@resource
def value() -> int:
    return 123

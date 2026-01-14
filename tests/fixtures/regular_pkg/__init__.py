"""A regular package for testing."""

from mixinject import resource


@resource
def pkg_value() -> str:
    return "from_pkg"

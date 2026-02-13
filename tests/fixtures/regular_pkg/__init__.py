"""A regular package for testing."""

from ol import public, resource


@public
@resource
def pkg_value() -> str:
    return "from_pkg"

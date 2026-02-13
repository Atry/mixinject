"""A regular package for testing."""

from overlay.language import public, resource


@public
@resource
def pkg_value() -> str:
    return "from_pkg"

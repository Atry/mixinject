"""A child module within regular_pkg."""

from ol import public, resource


@public
@resource
def child_value() -> str:
    return "from_child"

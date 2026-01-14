"""A child module within regular_pkg."""

from mixinject import resource


@resource
def child_value() -> str:
    return "from_child"

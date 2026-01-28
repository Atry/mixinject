"""Grandchild module (two levels deep)."""
from mixinject import resource


@resource
def grandchild_value() -> str:
    return "from_grandchild"

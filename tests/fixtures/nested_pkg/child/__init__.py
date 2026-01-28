"""Child package (one level deep)."""
from mixinject import resource


@resource
def child_value() -> str:
    return "from_child"

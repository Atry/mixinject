"""Child package (one level deep)."""
from ol import public, resource


@public
@resource
def child_value() -> str:
    return "from_child"

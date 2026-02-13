"""Child package (one level deep)."""
from overlay.language import public, resource


@public
@resource
def child_value() -> str:
    return "from_child"

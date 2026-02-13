"""Branch 0: Defines merges for deduplicated_tags and union_mount_point."""

from typing import Callable, Iterator

from ol import merge, public, scope


@public
@merge
def deduplicated_tags() -> Callable[[Iterator[str]], frozenset[str]]:
    return frozenset


@public
@scope
class union_mount_point:
    """Base empty scope - other branches will merge their definitions into this."""

    pass

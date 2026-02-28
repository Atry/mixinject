"""PragmaBase: defines the aggregation strategy for startup_pragmas."""

from typing import Callable, Iterator

from mixinv2 import merge, public


@public
@merge
def startup_pragmas() -> Callable[[Iterator[str]], frozenset[str]]:
    return frozenset

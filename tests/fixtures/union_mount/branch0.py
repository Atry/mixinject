"""Branch 0: Defines aggregators for deduplicated_tags and union_mount_point."""

from typing import Callable, Iterator

from mixinject import CachedProxy, Component, aggregator


@aggregator
def deduplicated_tags() -> Callable[[Iterator[str]], frozenset[str]]:
    return frozenset


@aggregator
def union_mount_point() -> Callable[[Iterator[Component]], CachedProxy]:
    def create_proxy(components: Iterator[Component]) -> CachedProxy:
        return CachedProxy(components=frozenset(components))

    return create_proxy

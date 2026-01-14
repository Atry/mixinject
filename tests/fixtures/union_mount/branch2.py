"""Branch 2: Provides tag2 patch with dependency on another_dependency.

Note: @resource decorator returns a BuilderDefinition object, not a function,
so @staticmethod is not needed (Python's descriptor protocol only applies to functions).
"""

from mixinject import Component, patch, patches, resolve_root, resource


@patch
def deduplicated_tags(another_dependency: str) -> str:
    return f"tag2_{another_dependency}"


class Mixin2:
    @resource
    def bar(foo: str) -> str:
        return f"{foo}_bar"


@patches
def union_mount_point() -> frozenset[Component]:
    return resolve_root(Mixin2).components

"""Branch 1: Provides tag1 patch and another_dependency resource."""

from mixinject import patch, resource, scope


@patch
def deduplicated_tags() -> str:
    return "tag1"


@resource
def another_dependency() -> str:
    return "dependency_value"


@scope()
class union_mount_point:
    """Provides foo resource via @scope semigroup."""

    @resource
    def foo() -> str:
        return "foo"

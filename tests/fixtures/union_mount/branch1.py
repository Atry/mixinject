"""Branch 1: Provides tag1 patch and another_dependency resource."""

from overlay.language import patch, public, resource, scope


@patch
def deduplicated_tags() -> str:
    return "tag1"


@public
@resource
def another_dependency() -> str:
    return "dependency_value"


@public
@scope
class union_mount_point:
    """Provides foo resource via @scope semigroup."""

    @public
    @resource
    def foo() -> str:
        return "foo"

"""Branch 2: Provides tag2 patch with dependency on another_dependency.

Note: @resource decorator returns a MergerDefinition object, not a function,
so @staticmethod is not needed (Python's descriptor protocol only applies to functions).
"""

from ol import extern, patch, public, resource, scope


@extern
def another_dependency() -> str:
    ...


@patch
def deduplicated_tags(another_dependency: str) -> str:
    return f"tag2_{another_dependency}"


@public
@scope
class union_mount_point:
    """Provides bar resource via @scope semigroup, depending on foo from branch1."""

    @extern
    def foo() -> str: ...

    @public
    @resource
    def bar(foo: str) -> str:
        return f"{foo}_bar"

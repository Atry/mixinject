"""Union mount fixtures demonstrating merge and patches use cases."""

from mixinject import RelativeReference as R
from mixinject import extend, scope


@extend(
    R(levels_up=0, path=("branch0",)),
    R(levels_up=0, path=("branch1",)),
    R(levels_up=0, path=("branch2",)),
)
@scope
class combined:
    """Combined scope that extends branch0, branch1, and branch2 modules."""

    pass

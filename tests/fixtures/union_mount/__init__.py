"""Union mount fixtures demonstrating merge and patches use cases."""

from overlay.language import RelativeReference as R
from overlay.language import extend, public, scope


@extend(
    R(de_bruijn_index=0, path=("branch0",)),
    R(de_bruijn_index=0, path=("branch1",)),
    R(de_bruijn_index=0, path=("branch2",)),
)
@public
@scope
class combined:
    """Combined scope that extends branch0, branch1, and branch2 modules."""

    pass

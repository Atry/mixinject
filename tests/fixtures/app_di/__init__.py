"""app_di: package-based DI example mirroring the README @scope examples.

Modules mirror the README step-by-step walkthrough:
- sqlite_database    → SQLiteDatabase scope  (Step 1)
- pragmas/           → @patch / @merge examples (Step 2)
- user_repository/   → UserRepository scope  (Step 4)
- app_services/      → AppServices scope     (Step 4)

Composite scopes declared via @extend:
- step1_app          → sqlite_database + user_repository (Step 1)
- step4_request_app  → sqlite_database + user_repository + http_handlers (Step 4, no server)
- step4_app          → all four modules (Step 4, full stack)
"""

from overlay.language import RelativeReference as R
from overlay.language import extend, public, scope


@extend(
    R(de_bruijn_index=0, path=("sqlite_database",)),
    R(de_bruijn_index=0, path=("user_repository",)),
)
@public
@scope
class step1_app:
    pass


@extend(
    R(de_bruijn_index=0, path=("sqlite_database",)),
    R(de_bruijn_index=0, path=("user_repository",)),
    R(de_bruijn_index=0, path=("http_handlers",)),
)
@public
@scope
class step4_request_app:
    pass


@extend(
    R(de_bruijn_index=0, path=("sqlite_database",)),
    R(de_bruijn_index=0, path=("user_repository",)),
    R(de_bruijn_index=0, path=("http_handlers",)),
    R(de_bruijn_index=0, path=("network_server",)),
)
@public
@scope
class step4_app:
    pass

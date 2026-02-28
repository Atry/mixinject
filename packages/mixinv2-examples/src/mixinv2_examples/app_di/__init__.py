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

from mixinv2 import LexicalReference
from mixinv2 import extend, public, scope


# [docs:module-extend]
@extend(
    LexicalReference(path=("sqlite_database",)),
    LexicalReference(path=("user_repository",)),
)
@public
@scope
class step1_app:
    pass
# [/docs:module-extend]


@extend(
    LexicalReference(path=("sqlite_database",)),
    LexicalReference(path=("user_repository",)),
    LexicalReference(path=("http_handlers",)),
)
@public
@scope
class step4_request_app:
    pass


@extend(
    LexicalReference(path=("sqlite_database",)),
    LexicalReference(path=("user_repository",)),
    LexicalReference(path=("http_handlers",)),
    LexicalReference(path=("network_server",)),
)
@public
@scope
class step4_app:
    pass

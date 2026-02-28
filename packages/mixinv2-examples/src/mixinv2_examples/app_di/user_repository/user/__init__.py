"""UserRepository.User: composable data object — @scope used as a dataclass."""

from mixinv2 import extern, public


@public
@extern
def user_id() -> int: ...


@public
@extern
def name() -> str: ...

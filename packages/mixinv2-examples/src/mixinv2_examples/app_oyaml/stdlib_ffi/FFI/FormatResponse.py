"""template.format(total=user_count, current=current_user_name).encode() -> response_body"""

from mixinv2 import extern, public, resource


@extern
def response_template() -> str: ...


@extern
def user_count() -> int: ...


@extern
def current_user_name() -> str: ...


@public
@resource
def response_body(response_template: str, user_count: int, current_user_name: str) -> bytes:
    return response_template.format(total=user_count, current=current_user_name).encode()

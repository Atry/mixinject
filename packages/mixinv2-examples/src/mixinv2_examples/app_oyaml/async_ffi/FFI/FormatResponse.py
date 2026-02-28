"""template.format(total=user_count, current=current_user_name).encode() -> response_body"""

from collections.abc import Awaitable

from mixinv2 import extern, public, resource

from ._async_resource import async_resource


@extern
def response_template() -> Awaitable[str]: ...


@extern
def user_count() -> Awaitable[int]: ...


@extern
def current_user_name() -> Awaitable[str]: ...


@public
@resource
@async_resource
async def response_body(
    response_template: str, user_count: int, current_user_name: str
) -> bytes:
    return response_template.format(
        total=user_count, current=current_user_name
    ).encode()

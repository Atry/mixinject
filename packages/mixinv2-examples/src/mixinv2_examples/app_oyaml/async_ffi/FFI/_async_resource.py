"""@async_resource decorator for async FFI modules.

Wraps an async def's return value with asyncio.ensure_future.
All parameters are Awaitable — the wrapper awaits them before calling the
original function.  The coroutine result is scheduled as a Task via
ensure_future, so dependents receive a Task (not a coroutine) and can
safely depend on the same value from multiple places.
"""

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps


def async_resource(async_function: Callable) -> Callable:
    """Decorator: wraps an async def's return value with asyncio.ensure_future."""

    @wraps(async_function)
    def wrapper(**keyword_arguments: object) -> "asyncio.Task[object]":
        async def resolved() -> object:
            resolved_keyword_arguments = {
                key: (await value) if isinstance(value, Awaitable) else value
                for key, value in keyword_arguments.items()
            }
            return await async_function(**resolved_keyword_arguments)

        return asyncio.ensure_future(resolved())

    return wrapper

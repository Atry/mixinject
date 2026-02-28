"""connection.execute(sql, parameters).fetchone() -> single row"""

from collections.abc import Awaitable

import aiosqlite

from mixinv2 import extern, public, resource

from ._async_resource import async_resource


@extern
def connection() -> Awaitable[aiosqlite.Connection]: ...


@extern
def sql() -> Awaitable[str]: ...


@extern
def parameters() -> Awaitable[tuple]: ...


@public
@resource
@async_resource
async def row(
    connection: aiosqlite.Connection, sql: str, parameters: tuple
) -> tuple:
    cursor = await connection.execute(sql, parameters)
    result = await cursor.fetchone()
    assert result is not None, f"query returned no rows: {sql}"
    return result

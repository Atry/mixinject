"""connection.execute(sql).fetchall() -> single scalar value"""

from collections.abc import Awaitable

import aiosqlite

from mixinv2 import extern, public, resource

from ._async_resource import async_resource


@extern
def connection() -> Awaitable[aiosqlite.Connection]: ...


@extern
def sql() -> Awaitable[str]: ...


@public
@resource
@async_resource
async def scalar(connection: aiosqlite.Connection, sql: str) -> object:
    cursor = await connection.execute(sql)
    rows = await cursor.fetchall()
    row, = rows
    value, = row
    return value

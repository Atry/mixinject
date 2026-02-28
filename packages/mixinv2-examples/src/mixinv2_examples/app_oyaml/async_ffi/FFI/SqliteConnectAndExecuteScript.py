"""aiosqlite.connect(database_path) + executescript(setup_sql) -> connection"""

from collections.abc import Awaitable

import aiosqlite

from mixinv2 import extern, public, resource

from ._async_resource import async_resource


@extern
def database_path() -> Awaitable[str]: ...


@extern
def setup_sql() -> Awaitable[str]: ...


@public
@resource
@async_resource
async def connection(
    database_path: str, setup_sql: str
) -> aiosqlite.Connection:
    connection = await aiosqlite.connect(database_path)
    await connection.executescript(setup_sql)
    return connection

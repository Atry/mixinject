"""FFI: Async FFI adapters using aiosqlite + starlette.

Each module wraps exactly ONE async operation.
All business logic lives in .oyaml files — Python is only the FFI bridge.

Design rules (same as stdlib_ffi):
  1. One module per async operation — no business logic.
  2. Every input is @extern — wired by oyaml.
  3. One @public @resource output per module.

Async convention:
  - All @resource parameters may be Awaitable (Tasks from upstream).
  - All @resource return values are asyncio.Task (via @async_resource).
  - The @async_resource decorator awaits Awaitable parameters and wraps
    the coroutine result with asyncio.ensure_future.
"""

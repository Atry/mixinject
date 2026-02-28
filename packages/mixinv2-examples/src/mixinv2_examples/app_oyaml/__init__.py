"""app_oyaml: MIXINv2 web-app example.

Library.oyaml — business logic + abstract FFI declarations.
stdlib_ffi/FFI/ — Python stdlib FFI adapters (one module per scope).
async_ffi/FFI/ — Async FFI adapters using aiosqlite + starlette.
Apps.oyaml — sync integration entry points (inherits stdlib_ffi + Library).
AsyncApps.oyaml — async integration entry points (inherits async_ffi + Library).
"""

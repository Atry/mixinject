"""FFI: Atomic stdlib wrappers for the MIXINv2 web-app example.

Each module wraps exactly ONE Python stdlib / built-in call.
All business logic (SQL queries, string formatting, routing, composition)
lives in .oyaml files — Python is only the FFI bridge.

Design rules:
  1. One module per stdlib call — no business logic.
  2. Every input is @extern — wired by oyaml.
  3. One @public @resource output per module.
"""

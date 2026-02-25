"""
Parser for MIXINv2 specification files (YAML/JSON/TOML).

This module provides parsing of MIXINv2 files into Definition objects that can be
evaluated by the overlay runtime.

.. todo::
   Implement naming convention detection for automatic decorator inference.

   Variables whose first non-underscore character is lowercase should be
   translated to ``@resource`` instead of ``@scope``. Currently all parsed
   definitions are treated as scopes (``is_public=True``).

   Example naming convention in YAML::

       Nat:           # PascalCase → @scope
         predecessor: []  # lowercase → @resource (currently incorrect)
         _private:    []  # underscore + lowercase → private @resource

   **Once implemented, this will give us a language with the following properties:**

   - **Compile-time Turing complete**: The symbol tree construction can express
     arbitrary computations during compilation.
   - **AOT compiled programs are total**: All runtime computations terminate or
     are productive (for infinite structures).
   - **Supports circular references**: With lazy evaluation, resources can form
     cycles while remaining total.
   - **Lazy evaluation**: Resources are computed on-demand, enabling infinite
     structures and breaking circular dependencies.
   - **Structural recursion**: Tree structure + naming convention enforce that
     recursive calls are made only on structurally smaller values.

   This combination enables MIXINv2 to support both finite structures (via
   recursion/termination) and infinite structures (via corecursion/productivity),
   similar to Haskell's lazy evaluation or Coq's coinductive types.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Hashable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field
from functools import cached_property
from pathlib import Path
from typing import TypeAlias, final

import yaml

from overlay.language._core import (
    Definition,
    EndofunctionMergerDefinition,
    LexicalReference,
    QualifiedThisReference,
    ResourceReference,
    ScopeDefinition,
)

# JSON-compatible type aliases
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FileMixinDefinition(ScopeDefinition):
    """
    Definition for a mixin parsed from a MIXINv2 file.

    This holds the parsed properties from the file. The `underlying` field
    stores the raw parsed data, and properties are resolved lazily via
    __iter__ and __getitem__.
    """

    underlying: Mapping[str, JsonValue]
    """The parsed properties from the mixin definition."""

    scalar_values: tuple[JsonScalar, ...]
    """Scalar values inherited by this mixin."""

    source_file: Path
    """Path to the source file for error reporting."""

    def __iter__(self) -> Iterator[Hashable]:
        """Yield property names from this mixin."""
        yield from self.underlying.keys()

    def __len__(self) -> int:
        return len(self.underlying)

    def __getitem__(self, key: Hashable) -> Sequence[Definition]:
        """Get child definitions by property name."""
        assert isinstance(key, str)
        if key not in self.underlying:
            raise KeyError(key)

        value = self.underlying[key]
        parsed = parse_mixin_value(value, source_file=self.source_file)
        return _definitions_from_parsed(
            parsed=parsed, is_public=True, source_file=self.source_file
        )


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class ParsedMixinValue:
    """Result of parsing a single mixin value."""

    inheritances: tuple[ResourceReference, ...]
    """Inheritance references (bases)."""

    property_definitions: tuple[Mapping[str, JsonValue], ...]
    """Property definitions (multiple origins)."""

    scalar_values: tuple[JsonScalar, ...]
    """Scalar values."""


def parse_reference(array: list[JsonValue]) -> ResourceReference:
    """
    Parse a MIXINv2 array reference into a ResourceReference.

    Distinguishes between:
    - Regular inheritance: [str, str, ...] → LexicalReference
    - Qualified this: [str, null, str, ...] → QualifiedThisReference

    :param array: The array from the MIXINv2 file.
    :return: A ResourceReference.
    :raises ValueError: If the array is empty or has invalid format.
    """
    if not array:
        raise ValueError("Reference array must not be empty")

    # Check for qualified this: [str, null, str, ...]
    if len(array) >= 2 and array[1] is None:
        self_name = array[0]
        if not isinstance(self_name, str):
            raise ValueError(
                f"Qualified this self_name must be a string, got {type(self_name).__name__}"
            )
        path_elements: list[str] = []
        for element in array[2:]:
            if not isinstance(element, str):
                raise ValueError(
                    f"Reference path element must be a string, got {type(element).__name__}: {element!r}"
                )
            path_elements.append(element)
        return QualifiedThisReference(self_name=self_name, path=tuple(path_elements))

    # Regular inheritance: all elements must be strings
    path_elements = []
    for element in array:
        if not isinstance(element, str):
            raise ValueError(
                f"Reference path element must be a string, got {type(element).__name__}: {element!r}"
            )
        path_elements.append(element)
    return LexicalReference(path=tuple(path_elements))


def _is_reference_array(value: JsonValue) -> bool:
    """
    Check if a value is a reference array (inheritance or qualified this).

    In MIXINv2, arrays are ONLY used for references:
    - Inheritance: [str, str, ...] - all strings
    - Qualified this: [str, null, str, ...] - string, null, then strings

    MIXINv2 does not have first-class list/array type.
    """
    if not isinstance(value, list) or len(value) == 0:
        return False
    # Check for qualified this: [str, null, ...]
    if len(value) >= 2 and isinstance(value[0], str) and value[1] is None:
        return all(isinstance(e, str) for e in value[2:])
    # Check for regular inheritance: all strings
    return all(isinstance(e, str) for e in value)


def _parse_array_item(item: JsonValue) -> tuple[
    ResourceReference | None, Mapping[str, JsonValue] | None, JsonScalar | None
]:
    """
    Parse a single item from a mixin array.

    :return: Tuple of (inheritance_ref, properties, scalar_value).
             Only one will be non-None.
    """
    if isinstance(item, list):
        return (parse_reference(item), None, None)
    if isinstance(item, dict):
        return (None, item, None)
    if isinstance(item, str | int | float | bool) or item is None:
        return (None, None, item)
    raise ValueError(f"Unexpected item type in mixin array: {type(item).__name__}")


def _parse_array_value(items: list[JsonValue]) -> ParsedMixinValue:
    """Parse a mixin array (not a reference array) into components."""
    parsed_items = tuple(_parse_array_item(item) for item in items)

    inheritances = tuple(ref for ref, _, _ in parsed_items if ref is not None)
    property_definitions = tuple(props for _, props, _ in parsed_items if props is not None)
    scalar_values = tuple(scalar for _, _, scalar in parsed_items if scalar is not None)

    return ParsedMixinValue(
        inheritances=inheritances,
        property_definitions=property_definitions,
        scalar_values=scalar_values,
    )


def _make_scalar_resource(
    scalar_value: JsonScalar | tuple[JsonScalar, ...],
    is_public: bool,
) -> EndofunctionMergerDefinition[object]:
    """Create an EndofunctionMergerDefinition that returns a scalar value.

    This is the oyaml equivalent of ``@resource def field(): return scalar_value``.
    """
    return EndofunctionMergerDefinition(
        inherits=(),
        function=lambda: scalar_value,
        is_eager=False,
        is_public=is_public,
    )


def _definitions_from_parsed(
    *,
    parsed: ParsedMixinValue,
    is_public: bool,
    source_file: Path,
) -> tuple[Definition, ...]:
    """Convert a ParsedMixinValue into a tuple of Definitions.

    When the parsed value contains only scalar values (no property definitions
    and no inheritances), produces EndofunctionMergerDefinition resources so
    the runtime evaluates them as resource values rather than empty scopes.

    Otherwise, produces FileMixinDefinition scopes as before.
    """
    if parsed.property_definitions:
        return tuple(
            FileMixinDefinition(
                inherits=parsed.inheritances if index == 0 else (),
                is_public=is_public,
                underlying=properties,
                scalar_values=parsed.scalar_values if index == 0 else (),
                source_file=source_file,
            )
            for index, properties in enumerate(parsed.property_definitions)
        )

    # No property definitions — could be pure scalar, pure inheritance, or both.
    if parsed.scalar_values and not parsed.inheritances:
        # Pure scalar: emit as @resource returning the value.
        # Multiple scalars in a single field are combined into a tuple.
        if len(parsed.scalar_values) == 1:
            scalar_value, = parsed.scalar_values
        else:
            scalar_value = parsed.scalar_values
        return (_make_scalar_resource(scalar_value, is_public=is_public),)

    # Inheritance (with or without scalars): emit as ScopeDefinition.
    return (
        FileMixinDefinition(
            inherits=parsed.inheritances,
            is_public=is_public,
            underlying={},
            scalar_values=parsed.scalar_values,
            source_file=source_file,
        ),
    )


def parse_mixin_value(
    value: JsonValue,
    source_file: Path,  # noqa: ARG001 - reserved for future error messages
) -> ParsedMixinValue:
    """
    Parse a MIXINv2 value into inheritances, properties, and scalar values.

    In MIXINv2, arrays are ONLY used for references (inheritance or qualified this).
    There is no first-class list type in MIXINv2.

    A mixin value can be:
    - A reference array: [str, str, ...] or [str, null, str, ...] → inheritance
    - An array containing nested references, property objects, and scalars
    - An object containing only properties
    - A scalar value

    :param value: The parsed JSON value from the mixin file.
    :param source_file: Path to source file for error reporting.
    :return: ParsedMixinValue with separated components.
    """
    del source_file  # Reserved for future error messages

    if isinstance(value, list):
        if _is_reference_array(value):
            # Single inheritance reference
            return ParsedMixinValue(
                inheritances=(parse_reference(value),),
                property_definitions=(),
                scalar_values=(),
            )
        # Array with mixed content
        return _parse_array_value(value)

    if isinstance(value, dict):
        # Object format: all properties, no inheritances
        return ParsedMixinValue(
            inheritances=(),
            property_definitions=(value,),
            scalar_values=(),
        )

    if isinstance(value, str | int | float | bool) or value is None:
        # Single scalar value
        return ParsedMixinValue(
            inheritances=(),
            property_definitions=(),
            scalar_values=(value,),
        )

    raise ValueError(f"Unexpected mixin value type: {type(value).__name__}")


def _parse_top_level_mixin(
    mixin_name: str,
    mixin_value: JsonValue,
    file_path: Path,
) -> tuple[str, Sequence[Definition]]:
    """Parse a single top-level mixin entry."""
    if not isinstance(mixin_name, str):
        raise ValueError(f"Mixin name must be a string, got {type(mixin_name).__name__}")

    parsed = parse_mixin_value(mixin_value, source_file=file_path)
    return (
        mixin_name,
        _definitions_from_parsed(
            parsed=parsed, is_public=True, source_file=file_path
        ),
    )


def load_overlay_file(file_path: Path) -> JsonValue:
    """
    Load and parse a MIXINv2 file (YAML/JSON/TOML) into raw JSON data.

    :param file_path: Path to the MIXINv2 file.
    :return: The parsed JSON-compatible data (dict, list, or scalar).
    :raises ValueError: If the file format is not recognized.
    """
    content = file_path.read_text(encoding="utf-8")

    name = file_path.name.lower()
    if (
        name.endswith(".oyaml")
        or name.endswith(".oyml")
        or name.endswith(".mixin.yaml")
        or name.endswith(".mixin.yml")
    ):
        return yaml.load(content, Loader=yaml.CSafeLoader)  # noqa: S506
    elif name.endswith(".ojson") or name.endswith(".mixin.json"):
        return json.loads(content)
    elif name.endswith(".otoml") or name.endswith(".mixin.toml"):
        return tomllib.loads(content)
    else:
        raise ValueError(
            f"Unrecognized MIXINv2 file format: {file_path.name}. "
            f"Expected .mixin.yaml, .mixin.json, .mixin.toml, .oyaml, .ojson, or .otoml"
        )


def parse_mixin_file(file_path: Path) -> Mapping[str, Sequence[Definition]]:
    """
    Parse a MIXINv2 file (YAML/JSON/TOML) containing named top-level mixins.

    The file must contain a mapping at the top level, where each key is a mixin
    name. For files where the top level is a mixin definition itself (list or
    scalar), use :func:`parse_mixin_value` with :func:`load_overlay_file` instead.

    :param file_path: Path to the mixin file.
    :return: Mapping of top-level mixin names to sequences of definitions (multiple origins).
    :raises ValueError: If the file format is not recognized or top level is not a mapping.
    """
    data = load_overlay_file(file_path)

    if not isinstance(data, dict):
        raise ValueError(
            f"Overlay file must contain a mapping at top level, got {type(data).__name__}"
        )

    return dict(
        _parse_top_level_mixin(mixin_name, mixin_value, file_path)
        for mixin_name, mixin_value in data.items()
    )


@final
class OverlayFileScopeDefinition(ScopeDefinition):
    """
    Lazy definition for an overlay file.

    Handles both mapping-at-top-level (dict) and value-at-top-level (non-dict)
    files. All parsing is deferred to ``@cached_property`` accessors.

    Not a ``@dataclass`` because ``inherits`` must be lazily computed from file
    content via ``@cached_property``, which conflicts with the inherited
    ``bases`` dataclass field from ``ScopeDefinition``.
    """

    __slots__ = ("source_file",)

    source_file: Path
    """Path to the overlay file."""

    def __init__(self, *, is_public: bool, source_file: Path) -> None:
        object.__setattr__(self, "is_public", is_public)
        object.__setattr__(self, "source_file", source_file)

    @cached_property
    def _loaded_data(self) -> JsonValue:
        return load_overlay_file(self.source_file)

    @cached_property
    def _non_dict_parsed(self) -> ParsedMixinValue:
        data = self._loaded_data
        assert not isinstance(data, dict)
        return parse_mixin_value(data, source_file=self.source_file)

    @cached_property
    def inherits(self) -> tuple[ResourceReference, ...]:
        data = self._loaded_data
        if isinstance(data, dict):
            return ()
        return self._non_dict_parsed.inheritances

    @cached_property
    def _dict_parsed(self) -> Mapping[str, Sequence[Definition]]:
        data = self._loaded_data
        assert isinstance(data, dict)
        return dict(
            _parse_top_level_mixin(name, value, self.source_file)
            for name, value in data.items()
        )

    def __iter__(self) -> Iterator[Hashable]:
        if isinstance(self._loaded_data, dict):
            yield from self._dict_parsed.keys()
        else:
            seen: set[str] = set()
            for properties in self._non_dict_parsed.property_definitions:
                for key in properties:
                    if key not in seen:
                        seen.add(key)
                        yield key

    def __getitem__(self, key: Hashable) -> Sequence[Definition]:
        assert isinstance(key, str)

        if isinstance(self._loaded_data, dict):
            parsed = self._dict_parsed
            if key not in parsed:
                raise KeyError(key)
            return parsed[key]

        # Non-dict file: collect definitions from all property_definitions
        definitions: list[Definition] = []
        for properties in self._non_dict_parsed.property_definitions:
            if key not in properties:
                continue
            value = properties[key]
            child_parsed = parse_mixin_value(value, source_file=self.source_file)
            definitions.extend(
                _definitions_from_parsed(
                    parsed=child_parsed,
                    is_public=True,
                    source_file=self.source_file,
                )
            )

        if not definitions:
            raise KeyError(key)
        return tuple(definitions)

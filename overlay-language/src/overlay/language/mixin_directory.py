"""
Directory-based Overlay file discovery and evaluation.

This module provides support for evaluating Overlay files from filesystem
directories (not Python packages).
"""

from __future__ import annotations

from collections.abc import Hashable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, final

from overlay.language import (
    Definition,
    MixinSymbol,
    OuterSentinel,
    ScopeDefinition,
)
from overlay.language.mixin_parser import (
    OverlayFileScopeDefinition,
)

if TYPE_CHECKING:
    from overlay.language import runtime


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class DirectoryMixinDefinition(ScopeDefinition):
    """
    Scope definition for a directory of Overlay files.

    Recursively discovers *.oyaml/ojson/otoml files and subdirectories.
    """

    underlying: Path
    """The directory path."""

    @cached_property
    def _mixin_files(self) -> Mapping[str, Path]:
        """Discover *.oyaml/ojson/otoml files in the directory."""
        result: dict[str, Path] = {}
        if not self.underlying.is_dir():
            return result

        overlay_extensions = (".oyaml", ".oyml", ".ojson", ".otoml")
        for file_path in self.underlying.iterdir():
            if not file_path.is_file():
                continue
            name_lower = file_path.name.lower()
            for extension in overlay_extensions:
                if name_lower.endswith(extension):
                    # Extract stem: Foo.oyaml -> Foo
                    stem = file_path.name[: -len(extension)]
                    if stem not in result:
                        result[stem] = file_path
                    break
        return result

    @cached_property
    def _subdirectories(self) -> Mapping[str, Path]:
        """Discover subdirectories."""
        result: dict[str, Path] = {}
        if not self.underlying.is_dir():
            return result

        for entry in self.underlying.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                result[entry.name] = entry
        return result

    def __iter__(self) -> Iterator[Hashable]:
        """Yield mixin file stems and subdirectory names."""
        yield from self._mixin_files.keys()
        yield from self._subdirectories.keys()

    def __len__(self) -> int:
        return len(self._mixin_files) + len(self._subdirectories)

    def __getitem__(self, key: Hashable) -> Sequence[Definition]:
        """Get definitions by key name."""
        assert isinstance(key, str)
        definitions: list[Definition] = []

        # Check for mixin file
        mixin_file = self._mixin_files.get(key)
        if mixin_file is not None:
            definitions.append(
                OverlayFileScopeDefinition(
                    is_public=self.is_public,
                    source_file=mixin_file,
                )
            )

        # Check for subdirectory
        subdir = self._subdirectories.get(key)
        if subdir is not None:
            definitions.append(
                DirectoryMixinDefinition(
                    inherits=(),
                    is_public=self.is_public,
                    underlying=subdir,
                )
            )

        if not definitions:
            raise KeyError(key)

        return tuple(definitions)


def evaluate_mixin_directory(directory: Path) -> "runtime.Scope":
    """
    Evaluate a directory of MIXIN files into a Scope.

    :param directory: Path to the directory containing MIXIN files.
    :return: A Scope containing the evaluated mixins.
    :raises ValueError: If the path is not a directory.
    """
    if not directory.is_dir():
        raise ValueError(f"Path is not a directory: {directory}")

    from overlay.language import runtime

    root_definition = DirectoryMixinDefinition(
        inherits=(),
        is_public=True,
        underlying=directory,
    )
    root_symbol = MixinSymbol(origin=(root_definition,))
    root_mixin = runtime.Mixin(
        symbol=root_symbol,
        outer=OuterSentinel.ROOT,
        kwargs=runtime.KwargsSentinel.STATIC,
    )
    result = root_mixin.evaluated
    assert isinstance(result, runtime.Scope)
    return result

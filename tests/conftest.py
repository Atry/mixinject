"""Test utilities and fixtures for mixinject tests."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final, TypeVar, final

from typing_extensions import override

from mixinject import Merger, Patcher

TPatch_contra = TypeVar("TPatch_contra", contravariant=True)
TResult_co = TypeVar("TResult_co", covariant=True)
TPatch_co = TypeVar("TPatch_co", covariant=True)


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FunctionPatcher(Patcher[TPatch_co]):
    """Test utility: Patcher using generator function."""

    patch_generator: Final[Callable[[], Iterator[TPatch_co]]]

    @override
    def __iter__(self) -> Iterator[TPatch_co]:
        return self.patch_generator()


@final
@dataclass(frozen=True, kw_only=True, slots=True, weakref_slot=True)
class FunctionMerger(Merger[TPatch_contra, TResult_co]):
    """Test utility: Merger using custom aggregation function."""

    aggregation_function: Final[Callable[[Iterator[TPatch_contra]], TResult_co]]

    @override
    def merge(self, patches: Iterator[TPatch_contra]) -> TResult_co:
        return self.aggregation_function(patches)

from typing import Protocol

from overlay.language import (
    LexicalReference,
    MappingScopeDefinition,
    extend,
    merge,
    patch,
    patch_many,
    public,
    scope,
)


class _NatScope(Protocol):
    pythonValues: frozenset[int]


class _BinNatScope(Protocol):
    pythonValues: frozenset[int]


@public
@extend(LexicalReference(path=("NatData",)))
@scope
class NatToPython:
    @public
    @scope
    class NatFactory:
        @public
        @scope
        class Product:
            @public
            @merge
            @staticmethod
            def pythonValues():
                return frozenset

        @public
        @scope
        class Zero:
            @public
            @patch
            @staticmethod
            def pythonValues():
                return 0

        @public
        @scope
        class Successor:
            @public
            @patch_many
            @staticmethod
            def pythonValues(predecessor: _NatScope):
                return (value + 1 for value in predecessor.pythonValues)


@public
@extend(LexicalReference(path=("BinNatData",)))
@scope
class BinNatToPython:
    @public
    @scope
    class BinNatFactory:
        @public
        @scope
        class Product:
            @public
            @merge
            @staticmethod
            def pythonValues():
                return frozenset

        @public
        @scope
        class Zero:
            @public
            @patch
            @staticmethod
            def pythonValues():
                return 0

        @public
        @scope
        class Even:
            @public
            @patch_many
            @staticmethod
            def pythonValues(half: _BinNatScope):
                return (value * 2 for value in half.pythonValues)

        @public
        @scope
        class Odd:
            @public
            @patch_many
            @staticmethod
            def pythonValues(halfOfPredecessor: _BinNatScope):
                return (value * 2 + 1 for value in halfOfPredecessor.pythonValues)


@public
@extend(LexicalReference(path=("BooleanData",)))
@scope
class BooleanToPython:
    BooleanFactory = MappingScopeDefinition(
        inherits=(),
        is_public=True,
        underlying={
            "Product": MappingScopeDefinition(
                inherits=(),
                is_public=True,
                underlying={
                    "pythonValues": public(merge(lambda: frozenset)),
                },
            ),
            "True": MappingScopeDefinition(
                inherits=(),
                is_public=True,
                underlying={
                    "pythonValues": public(patch(lambda: True)),
                },
            ),
            "False": MappingScopeDefinition(
                inherits=(),
                is_public=True,
                underlying={
                    "pythonValues": public(patch(lambda: False)),
                },
            ),
        },
    )

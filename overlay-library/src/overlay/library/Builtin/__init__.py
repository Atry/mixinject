from overlay.language import (
    LexicalReference,
    MappingScopeDefinition,
    extend,
    extern,
    public,
    resource,
    scope,
)
from overlay.language.runtime import Scope


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
            @scope
            class ToPython:
                @public
                @extern
                @staticmethod
                def pythonValue() -> int: ...

        @public
        @scope
        class Zero:
            @public
            @scope
            class ToPython:
                @public
                @resource
                @staticmethod
                def pythonValue() -> int:
                    return 0

        @public
        @scope
        class Successor:
            @public
            @scope
            class ToPython:
                @public
                @resource
                @staticmethod
                def pythonValue(predecessor: Scope) -> int:
                    return predecessor.ToPython.pythonValue + 1


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
            @scope
            class ToPython:
                @public
                @extern
                @staticmethod
                def pythonValue() -> int: ...

        @public
        @scope
        class Zero:
            @public
            @scope
            class ToPython:
                @public
                @resource
                @staticmethod
                def pythonValue() -> int:
                    return 0

        @public
        @scope
        class Even:
            @public
            @scope
            class ToPython:
                @public
                @resource
                @staticmethod
                def pythonValue(half: Scope) -> int:
                    return half.ToPython.pythonValue * 2

        @public
        @scope
        class Odd:
            @public
            @scope
            class ToPython:
                @public
                @resource
                @staticmethod
                def pythonValue(half: Scope) -> int:
                    return half.ToPython.pythonValue * 2 + 1


@scope
class _BooleanApi:
    @public
    @scope
    class ToPython:
        @public
        @extern
        @staticmethod
        def pythonValue() -> bool: ...


@public
@scope
class _TrueToPython:
    @public
    @scope
    class ToPython:
        @public
        @resource
        @staticmethod
        def pythonValue() -> bool:
            return True


@public
@scope
class _FalseToPython:
    @public
    @scope
    class ToPython:
        @public
        @resource
        @staticmethod
        def pythonValue() -> bool:
            return False


BooleanToPython = MappingScopeDefinition(
    bases=(LexicalReference(path=("BooleanData",)),),
    is_public=True,
    underlying={
        "BooleanFactory": MappingScopeDefinition(
            bases=(),
            is_public=True,
            underlying={
                "Product": _BooleanApi,
                "True": _TrueToPython,
                "False": _FalseToPython,
            },
        ),
    },
)

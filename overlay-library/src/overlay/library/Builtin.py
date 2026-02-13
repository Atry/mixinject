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
@extend(LexicalReference(path=("Nat",)))
@scope
class NatToPython:
    @public
    @scope
    class Nat:
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
    bases=(),
    is_public=True,
    underlying={
        "Boolean": _BooleanApi,
        "True": _TrueToPython,
        "False": _FalseToPython,
    },
)

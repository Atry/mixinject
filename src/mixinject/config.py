from dataclasses import dataclass
from enum import Enum, auto


class InitializationTiming(Enum):
    LAZY = auto()
    """
    The resource is created when it is first accessed.
    """

    POST_INIT = auto()
    """
    The resource is created in ``Proxy.__post_init__``.
    """
    ENTER = auto()
    """
    The resource is created in ``Proxy.__enter__`` or ``Proxy.__aenter__``, depending on whether the resource is async.
    """


@dataclass(kw_only=True, frozen=True, slots=True, weakref_slot=True)
class Lifecycle:
    is_weak_reference: bool
    """
    Whether the resource is cached using a weak reference.
    """

    initialization: InitializationTiming
    """
    When the resource is created.
    """


class LifecycleSentinel(Enum):
    EPHEMERAL = auto()
    """
    The resource is not cached, and is created every time it is accessed.
    """


@dataclass(kw_only=True, frozen=True, slots=True, weakref_slot=True)
class ResourceConfig:
    lifecycle: Lifecycle | LifecycleSentinel
    is_async: bool
    """
    Whether the resource is async.

    When lifecycle is not EPHEMERAL, the resource (possibly after ``async_enter_context``) is converted to a Future when is_async is True.
    """

    is_contextmanager: bool
    """
    Whether the resource is a context manager.

    If True, the ``TResult`` is either a ``ContextManager`` or ``AsyncContextManager``, and should be registered with ``proxy.exit_stack.enter_context``` or ``proxy.exit_stack.async_enter_context`` depending on ``is_async``.
    """

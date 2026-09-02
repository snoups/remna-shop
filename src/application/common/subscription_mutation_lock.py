from contextlib import AbstractAsyncContextManager
from typing import Protocol


class SubscriptionMutationLockLostError(RuntimeError):
    """Raised when a live subscription mutation loses its distributed lease."""


class SubscriptionMutationLock(Protocol):
    def hold(self, user_id: int) -> AbstractAsyncContextManager[None]: ...

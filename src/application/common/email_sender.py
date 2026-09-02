from typing import Protocol, runtime_checkable


@runtime_checkable
class EmailSender(Protocol):
    @property
    def is_enabled(self) -> bool: ...

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        message_id: str | None = None,
    ) -> None: ...

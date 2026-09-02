from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import src.application.services.remnawave as remnawave_module
from src.application.services.remnawave import RemnaNodeEvent, RemnaWebhookService


def _service() -> RemnaWebhookService:
    service = object.__new__(RemnaWebhookService)
    service.event_bus = SimpleNamespace(publish=AsyncMock())
    return service


@pytest.mark.parametrize(
    "event",
    [
        RemnaNodeEvent.CREATED,
        RemnaNodeEvent.MODIFIED,
        RemnaNodeEvent.DISABLED,
        RemnaNodeEvent.ENABLED,
        RemnaNodeEvent.DELETED,
    ],
)
async def test_known_informational_node_events_do_not_emit_warnings(
    event: RemnaNodeEvent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_logger = SimpleNamespace(info=Mock(), debug=Mock(), warning=Mock())
    monkeypatch.setattr(remnawave_module, "logger", test_logger)
    service = _service()

    await service.handle_node_event(event, SimpleNamespace(name="test-node"))

    test_logger.debug.assert_called_once()
    test_logger.warning.assert_not_called()
    service.event_bus.publish.assert_not_awaited()


async def test_unknown_node_event_remains_visible_as_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_logger = SimpleNamespace(info=Mock(), debug=Mock(), warning=Mock())
    monkeypatch.setattr(remnawave_module, "logger", test_logger)
    service = _service()

    await service.handle_node_event("node.future_event", SimpleNamespace(name="test-node"))

    test_logger.warning.assert_called_once()
    service.event_bus.publish.assert_not_awaited()

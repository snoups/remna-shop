import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import HTTPException

from src.infrastructure.remnapy_compat import apply_remnapy_contract_compatibility
from src.web.endpoints import remnawave as endpoint


class _Request:
    headers = {"x-remnawave-signature": "test"}

    def __init__(self, payload: dict | None = None) -> None:
        self._body = json.dumps(payload or {}).encode()

    async def body(self) -> bytes:
        return self._body


def _config() -> SimpleNamespace:
    secret = SimpleNamespace(get_secret_value=lambda: "test-secret")
    return SimpleNamespace(
        remnawave=SimpleNamespace(webhook_secret=secret),
        build=SimpleNamespace(data={}),
    )


def _hwid_webhook_payload(**device_owner: object) -> dict:
    return {
        "event": "user_hwid_devices.added",
        "timestamp": "2026-08-20T10:00:00Z",
        "data": {
            "user": {
                "uuid": "d1dc2477-01e7-4847-9400-79ae63d5a4b0",
                "id": 42,
                "shortUuid": "contract-check",
                "username": "contract-check",
                "status": "ACTIVE",
                "userTraffic": {"usedTrafficBytes": 0, "lifetimeUsedTrafficBytes": 0},
                "trafficLimitBytes": 0,
                "trafficLimitStrategy": "NO_RESET",
                "expireAt": "2026-09-20T10:00:00Z",
                "trojanPassword": "contract-check",
                "vlessUuid": "e1e6d083-fd61-49c8-a289-dd44ca452229",
                "ssPassword": "contract-check",
                "lastTriggeredThreshold": 0,
                "subscriptionUrl": "https://vpn.example.com/sub/contract-check",
                "createdAt": "2026-08-20T10:00:00Z",
                "updatedAt": "2026-08-20T10:00:00Z",
                "activeInternalSquads": [],
            },
            "hwidUserDevice": {
                "hwid": "webhook-device",
                "createdAt": "2026-08-20T10:00:00Z",
                "updatedAt": "2026-08-20T10:00:00Z",
                **device_owner,
            },
        },
    }


@pytest.mark.asyncio
async def test_invalid_webhook_signature_stays_unauthorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        endpoint.WebhookUtility,
        "validate_webhook_with_headers",
        lambda **_: False,
    )
    service = SimpleNamespace(handle_device_event=AsyncMock())
    publisher = SimpleNamespace(publish=AsyncMock())

    with pytest.raises(HTTPException) as error:
        await endpoint._process_remnawave_webhook(_Request(), _config(), service, publisher)

    assert error.value.status_code == 401
    service.handle_device_event.assert_not_awaited()
    publisher.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_signed_unsupported_contract_is_retryable_and_alerted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        endpoint.WebhookUtility,
        "validate_webhook_with_headers",
        lambda **_: True,
    )
    monkeypatch.setattr(
        endpoint.WebhookUtility,
        "parse_webhook",
        lambda **_: (_ for _ in ()).throw(ValueError("unsupported contract")),
    )
    service = SimpleNamespace(handle_device_event=AsyncMock())
    publisher = SimpleNamespace(publish=AsyncMock())

    with pytest.raises(HTTPException) as error:
        await endpoint._process_remnawave_webhook(_Request(), _config(), service, publisher)

    assert error.value.status_code == 503
    service.handle_device_event.assert_not_awaited()
    publisher.publish.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("nested_uuid", "nested_id"),
    [
        (UUID("693269d4-df89-41c5-a8b7-a94fae6eea63"), None),
        (None, 99),
    ],
)
async def test_hwid_owner_mismatch_is_retryable_and_not_processed(
    monkeypatch: pytest.MonkeyPatch,
    nested_uuid: UUID | None,
    nested_id: int | None,
) -> None:
    user = SimpleNamespace(uuid=UUID("d1dc2477-01e7-4847-9400-79ae63d5a4b0"), id=42)
    device = SimpleNamespace(user_uuid=nested_uuid, user_id=nested_id)
    event = SimpleNamespace(user=user, hwid_user_device=device)
    payload = SimpleNamespace(event="user_hwid_devices.added")
    monkeypatch.setattr(
        endpoint.WebhookUtility,
        "validate_webhook_with_headers",
        lambda **_: True,
    )
    monkeypatch.setattr(endpoint.WebhookUtility, "parse_webhook", lambda **_: payload)
    monkeypatch.setattr(endpoint.WebhookUtility, "is_user_event", lambda _: False)
    monkeypatch.setattr(endpoint.WebhookUtility, "is_user_hwid_devices_event", lambda _: True)
    monkeypatch.setattr(endpoint.WebhookUtility, "get_typed_data", lambda _: event)
    service = SimpleNamespace(handle_device_event=AsyncMock())
    publisher = SimpleNamespace(publish=AsyncMock())

    with pytest.raises(HTTPException) as error:
        await endpoint._process_remnawave_webhook(_Request(), _config(), service, publisher)

    assert error.value.status_code == 503
    service.handle_device_event.assert_not_awaited()
    publisher.publish.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "device_owner",
    [
        {"userUuid": "693269d4-df89-41c5-a8b7-a94fae6eea63"},
        {"userId": 99},
    ],
)
async def test_real_hwid_payload_owner_mismatch_is_rejected_before_sdk_discards_it(
    monkeypatch: pytest.MonkeyPatch,
    device_owner: dict,
) -> None:
    apply_remnapy_contract_compatibility()
    monkeypatch.setattr(
        endpoint.WebhookUtility,
        "validate_webhook_with_headers",
        lambda **_: True,
    )
    service = SimpleNamespace(handle_device_event=AsyncMock())
    publisher = SimpleNamespace(publish=AsyncMock())

    with pytest.raises(HTTPException) as error:
        await endpoint._process_remnawave_webhook(
            _Request(_hwid_webhook_payload(**device_owner)),
            _config(),
            service,
            publisher,
        )

    assert error.value.status_code == 503
    service.handle_device_event.assert_not_awaited()
    publisher.publish.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "device_owner",
    [
        {},
        {"userUuid": "d1dc2477-01e7-4847-9400-79ae63d5a4b0"},
        {"userId": 42},
    ],
)
async def test_real_hwid_payload_matching_or_missing_owner_is_processed(
    monkeypatch: pytest.MonkeyPatch,
    device_owner: dict,
) -> None:
    apply_remnapy_contract_compatibility()
    monkeypatch.setattr(
        endpoint.WebhookUtility,
        "validate_webhook_with_headers",
        lambda **_: True,
    )
    service = SimpleNamespace(handle_device_event=AsyncMock())
    publisher = SimpleNamespace(publish=AsyncMock())

    response = await endpoint._process_remnawave_webhook(
        _Request(_hwid_webhook_payload(**device_owner)),
        _config(),
        service,
        publisher,
    )

    assert response.status_code == 200
    service.handle_device_event.assert_awaited_once()
    publisher.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_signed_schema_error_alert_and_log_do_not_disclose_payload_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apply_remnapy_contract_compatibility()
    monkeypatch.setattr(
        endpoint.WebhookUtility,
        "validate_webhook_with_headers",
        lambda **_: True,
    )
    payload = _hwid_webhook_payload()
    payload["data"]["user"]["ssPassword"] = "SUPERSECRET_SS"
    del payload["data"]["hwidUserDevice"]["createdAt"]
    service = SimpleNamespace(handle_device_event=AsyncMock())
    publisher = SimpleNamespace(publish=AsyncMock())
    safe_logger = SimpleNamespace(error=Mock(), warning=Mock(), exception=Mock())
    monkeypatch.setattr(endpoint, "logger", safe_logger)

    with pytest.raises(HTTPException) as error:
        await endpoint._process_remnawave_webhook(
            _Request(payload),
            _config(),
            service,
            publisher,
        )

    assert error.value.status_code == 503
    published_event = publisher.publish.await_args.args[0]
    assert "SUPERSECRET_SS" not in str(published_event.exception)
    assert "SUPERSECRET_SS" not in str(safe_logger.error.call_args)
    assert "createdAt:missing" in str(published_event.exception)
    service.handle_device_event.assert_not_awaited()


@pytest.mark.parametrize(
    ("nested_uuid", "nested_id"),
    [
        (UUID("d1dc2477-01e7-4847-9400-79ae63d5a4b0"), None),
        (None, 42),
        (None, None),
    ],
)
def test_matching_or_omitted_hwid_owner_is_accepted(
    nested_uuid: UUID | None,
    nested_id: int | None,
) -> None:
    user = SimpleNamespace(uuid=UUID("d1dc2477-01e7-4847-9400-79ae63d5a4b0"), id=42)
    device = SimpleNamespace(user_uuid=nested_uuid, user_id=nested_id)

    endpoint._validate_hwid_device_owner(user, device)


@pytest.mark.asyncio
async def test_informational_service_event_is_acknowledged_without_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = SimpleNamespace(event="service.login_attempt_success")
    monkeypatch.setattr(
        endpoint,
        "_parse_signed_remnawave_webhook",
        AsyncMock(return_value=payload),
    )
    monkeypatch.setattr(endpoint.WebhookUtility, "is_user_event", lambda _: False)
    monkeypatch.setattr(
        endpoint.WebhookUtility,
        "is_user_hwid_devices_event",
        lambda _: False,
    )
    monkeypatch.setattr(endpoint.WebhookUtility, "is_node_event", lambda _: False)
    monkeypatch.setattr(
        endpoint.WebhookUtility,
        "is_torrent_blocker_event",
        lambda _: False,
    )
    safe_logger = SimpleNamespace(debug=Mock(), warning=Mock(), exception=Mock())
    monkeypatch.setattr(endpoint, "logger", safe_logger)

    response = await endpoint._process_remnawave_webhook(
        _Request(),
        _config(),
        SimpleNamespace(),
        SimpleNamespace(publish=AsyncMock()),
    )

    assert response.status_code == 200
    safe_logger.debug.assert_called_once()
    safe_logger.warning.assert_not_called()

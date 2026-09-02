import json
import re
from typing import cast

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, Request, Response, status
from loguru import logger
from pydantic import ValidationError
from remnapy.controllers import WebhookUtility
from remnapy.models.webhook import (
    HwidUserDeviceDto,
    NodeDto,
    TorrentBlockerReportDto,
    UserDto,
    UserHwidDeviceEventDto,
    WebhookPayloadDto,
)

from src.application.common import EventPublisher
from src.application.events import ErrorEvent
from src.application.services import RemnaServiceEvent, RemnaWebhookService
from src.core.config import AppConfig
from src.core.constants import API_V1, REMNAWAVE_WEBHOOK_PATH

router = APIRouter(prefix=API_V1, include_in_schema=False)
_SAFE_CONTRACT_TOKEN = re.compile(r"[^a-zA-Z0-9_.-]+")
_INFORMATIONAL_EVENT_TYPES = frozenset(
    {
        RemnaServiceEvent.PANEL_STARTED.value,
        RemnaServiceEvent.LOGIN_ATTEMPT_SUCCESS.value,
    }
)
_SECURITY_EVENT_TYPES = frozenset({RemnaServiceEvent.LOGIN_ATTEMPT_FAILED.value})


class _WebhookContractError(ValueError):
    """A contract failure whose message is safe for logs and notifications."""


def _safe_contract_token(value: object) -> str:
    return _SAFE_CONTRACT_TOKEN.sub("?", str(value))[:64] or "unknown"


def _signed_webhook_contract_error(
    error: Exception,
    raw_payload: object,
) -> _WebhookContractError:
    event = "unknown"
    if isinstance(raw_payload, dict):
        event = _safe_contract_token(raw_payload.get("event", "unknown"))

    issues: list[str] = []
    if isinstance(error, ValidationError):
        for issue in error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )[:5]:
            location = ".".join(_safe_contract_token(part) for part in issue.get("loc", ()))
            error_type = _safe_contract_token(issue.get("type", "validation_error"))
            issues.append(f"{location or 'payload'}:{error_type}")
    elif isinstance(error, _WebhookContractError):
        issues.append(_safe_contract_token(error))

    suffix = f"; issues={','.join(issues)}" if issues else ""
    return _WebhookContractError(
        f"Signed Remnawave webhook contract rejected; event={event}{suffix}"
    )


def _validate_raw_hwid_device_owner(raw_payload: object) -> None:
    """Validate owner IDs before the pinned SDK can discard an unknown userId."""

    if not isinstance(raw_payload, dict):
        return
    event = raw_payload.get("event")
    if not isinstance(event, str) or not event.startswith("user_hwid_devices."):
        return

    data = raw_payload.get("data")
    if not isinstance(data, dict):
        return
    user = data.get("user")
    device = data.get("hwidUserDevice")
    if not isinstance(user, dict) or not isinstance(device, dict):
        return

    nested_uuid = device.get("userUuid")
    outer_uuid = user.get("uuid")
    if nested_uuid is not None and str(nested_uuid).lower() != str(outer_uuid).lower():
        raise _WebhookContractError("hwid_user_uuid_mismatch")

    nested_id = device.get("userId")
    outer_id = user.get("id")
    if nested_id is not None and str(nested_id) != str(outer_id):
        raise _WebhookContractError("hwid_user_id_mismatch")


def _validate_hwid_device_owner(user: UserDto, device: HwidUserDeviceDto) -> None:
    """Reject contradictory nested identity while allowing the signed wrapper to own it."""

    nested_uuid = getattr(device, "user_uuid", None)
    if nested_uuid is not None and nested_uuid != user.uuid:
        raise _WebhookContractError("hwid_user_uuid_mismatch")

    nested_id = getattr(device, "user_id", None)
    if nested_id is not None and nested_id != user.id:
        raise _WebhookContractError("hwid_user_id_mismatch")


async def _parse_signed_remnawave_webhook(
    request: Request,
    config: AppConfig,
    event_publisher: EventPublisher,
) -> WebhookPayloadDto:
    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
        is_valid = WebhookUtility.validate_webhook_with_headers(
            body=body,
            headers=dict(request.headers),
            webhook_secret=config.remnawave.webhook_secret.get_secret_value(),
        )
    except Exception as e:
        logger.exception(f"Webhook signature validation failed with error '{e}'")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    if not is_valid:
        logger.warning("Remnawave webhook signature validation failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    raw_payload: object = None
    try:
        raw_payload = json.loads(body)
        if not isinstance(raw_payload, dict):
            raise _WebhookContractError("payload_not_object")
        _validate_raw_hwid_device_owner(raw_payload)
        payload = WebhookUtility.parse_webhook(
            body=raw_payload,
            headers=dict(request.headers),
            webhook_secret=config.remnawave.webhook_secret.get_secret_value(),
            validate=False,
        )
    except Exception as e:
        safe_error = _signed_webhook_contract_error(e, raw_payload)
        logger.error(str(safe_error))
        error_event = ErrorEvent(**config.build.data, exception=safe_error)
        await event_publisher.publish(error_event)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    if not payload:
        error = _WebhookContractError("payload_empty")
        logger.error(str(error))
        error_event = ErrorEvent(**config.build.data, exception=error)
        await event_publisher.publish(error_event)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    return payload


async def _process_remnawave_webhook(
    request: Request,
    config: AppConfig,
    remna_webhook_service: RemnaWebhookService,
    event_publisher: EventPublisher,
) -> Response:
    payload = await _parse_signed_remnawave_webhook(request, config, event_publisher)

    try:
        if WebhookUtility.is_user_event(payload.event):
            user = cast(UserDto, WebhookUtility.get_typed_data(payload))
            expiration_hours = payload.meta.expiration if payload.meta else None
            await remna_webhook_service.handle_user_event(payload.event, user, expiration_hours)

        elif WebhookUtility.is_user_hwid_devices_event(payload.event):
            event = cast(UserHwidDeviceEventDto, WebhookUtility.get_typed_data(payload))
            _validate_hwid_device_owner(event.user, event.hwid_user_device)
            await remna_webhook_service.handle_device_event(
                payload.event,
                event.user,
                event.hwid_user_device,
            )

        elif WebhookUtility.is_node_event(payload.event):
            node = cast(NodeDto, WebhookUtility.get_typed_data(payload))
            await remna_webhook_service.handle_node_event(payload.event, node)

        elif WebhookUtility.is_torrent_blocker_event(payload.event):
            report = cast(TorrentBlockerReportDto, WebhookUtility.get_typed_data(payload))
            await remna_webhook_service.handle_torrent_blocker_event(report)

        elif payload.event in _INFORMATIONAL_EVENT_TYPES:
            logger.debug(f"Informational Remnawave event acknowledged: '{payload.event}'")

        elif payload.event in _SECURITY_EVENT_TYPES:
            logger.warning(f"Remnawave security event received: '{payload.event}'")

        else:
            logger.warning(f"Unhandled Remnawave event type '{payload.event}'")

    except Exception as e:
        logger.exception(f"Failed to process Remnawave webhook due to '{e}'")
        error_event = ErrorEvent(**config.build.data, exception=e)
        await event_publisher.publish(error_event)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response(status_code=status.HTTP_200_OK)


@router.post(REMNAWAVE_WEBHOOK_PATH)
@inject
async def remnawave_webhook(
    request: Request,
    config: FromDishka[AppConfig],
    remna_webhook_service: FromDishka[RemnaWebhookService],
    event_publisher: FromDishka[EventPublisher],
) -> Response:
    return await _process_remnawave_webhook(
        request=request,
        config=config,
        remna_webhook_service=remna_webhook_service,
        event_publisher=event_publisher,
    )

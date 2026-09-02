from uuid import UUID

from packaging.version import Version
from remnapy.models.hosts import GetAllHostsResponseDto, HostResponseDto
from remnapy.models.hwid import HwidDeviceDto
from remnapy.models.webhook import HwidUserDeviceDto, UserHwidDeviceEventDto, WebhookPayloadDto

from src.core.constants import REMNAWAVE_MAX_VERSION
from src.infrastructure.remnapy_compat import apply_remnapy_contract_compatibility


def test_remnawave_2_8_0_is_inside_the_verified_compatibility_range() -> None:
    assert Version("2.8.0") < REMNAWAVE_MAX_VERSION


def _host_payload() -> dict:
    return {
        "uuid": "c173c271-8756-4ac3-a235-ae4c009dd886",
        "viewPosition": 0,
        "remark": "contract-check",
        "address": "vpn.example.com",
        "port": 443,
        "path": None,
        "sni": None,
        "host": None,
        "alpn": None,
        "fingerprint": None,
        "muxParams": None,
        "sockoptParams": None,
        "inbound": {
            "configProfileUuid": None,
            "configProfileInboundUuid": None,
        },
        "serverDescription": None,
        "vlessRouteId": None,
        "shuffleHost": False,
        "mihomoX25519": False,
        "mihomoIpVersion": None,
        "nodes": [],
        "xrayJsonTemplateUuid": None,
    }


def _webhook_user_payload() -> dict:
    return {
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
    }


def test_host_contract_accepts_missing_optional_xhttp_params_and_tag() -> None:
    apply_remnapy_contract_compatibility()
    apply_remnapy_contract_compatibility()

    host = HostResponseDto.model_validate(_host_payload())
    hosts = GetAllHostsResponseDto.model_validate([_host_payload()])

    assert host.xhttp_extra_params is None
    assert host.tags == []
    assert hosts.root[0].xhttp_extra_params is None


def test_webhook_contract_preserves_top_level_expiration_metadata() -> None:
    payload = WebhookPayloadDto.from_dict(
        {
            "event": "custom.contract_check",
            "timestamp": "2026-08-20T10:00:00Z",
            "data": {},
            "meta": {"expiration": -24},
        }
    )

    assert payload.meta is not None
    assert payload.meta.expiration == -24


def test_hwid_contract_accepts_new_user_id_and_keeps_legacy_uuid() -> None:
    new_device = HwidDeviceDto.model_validate(
        {
            "hwid": "new-device",
            "userId": 42,
            "createdAt": "2026-08-20T10:00:00Z",
            "updatedAt": "2026-08-20T10:00:00Z",
        }
    )
    legacy_uuid = UUID("d1dc2477-01e7-4847-9400-79ae63d5a4b0")
    legacy_device = HwidDeviceDto.model_validate(
        {
            "hwid": "legacy-device",
            "userUuid": str(legacy_uuid),
            "createdAt": "2026-08-20T10:00:00Z",
            "updatedAt": "2026-08-20T10:00:00Z",
        }
    )

    assert new_device.user_id == 42
    assert new_device.user_uuid is None
    assert legacy_device.user_uuid == legacy_uuid
    assert legacy_device.user_id is None


def test_hwid_webhook_device_contract_accepts_missing_or_null_redundant_owner() -> None:
    apply_remnapy_contract_compatibility()
    apply_remnapy_contract_compatibility()
    payload = {
        "hwid": "webhook-device",
        "createdAt": "2026-08-20T10:00:00Z",
        "updatedAt": "2026-08-20T10:00:00Z",
    }

    missing_owner = HwidUserDeviceDto.model_validate(payload)
    null_owner = HwidUserDeviceDto.model_validate(payload | {"userUuid": None})

    assert missing_owner.user_uuid is None
    assert null_owner.user_uuid is None


def test_full_hwid_webhook_contract_accepts_device_without_redundant_owner() -> None:
    apply_remnapy_contract_compatibility()

    for event_name in ("user_hwid_devices.added", "user_hwid_devices.deleted"):
        payload = WebhookPayloadDto.from_dict(
            {
                "event": event_name,
                "timestamp": "2026-08-20T10:00:00Z",
                "data": {
                    "user": _webhook_user_payload(),
                    "hwidUserDevice": {
                        "hwid": "webhook-device",
                        "createdAt": "2026-08-20T10:00:00Z",
                        "updatedAt": "2026-08-20T10:00:00Z",
                    },
                },
            }
        )

        assert isinstance(payload.data, UserHwidDeviceEventDto)
        assert payload.data.hwid_user_device.user_uuid is None
        assert payload.data.user.id == 42

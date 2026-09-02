"""Narrow compatibility fixes for the pinned Remnawave SDK contract.

Keep these adjustments version-agnostic and idempotent so they become no-ops
as soon as remnapy declares the response fields optional itself.
"""

from typing import Any, cast, get_args

from loguru import logger
from remnapy.models.hosts import (
    CreateHostResponseDto,
    GetAllHostsResponseDto,
    GetOneHostResponseDto,
    HostResponseDto,
    HostsResponseDto,
    UpdateHostResponseDto,
)
from remnapy.models.webhook import HwidUserDeviceDto

_HOST_RESPONSE_MODELS = (
    HostResponseDto,
    CreateHostResponseDto,
    UpdateHostResponseDto,
    GetOneHostResponseDto,
    HostsResponseDto,
)
_XHTTP_FIELD = "xhttp_extra_params"
_XHTTP_ALIAS = "xhttpExtraParams"
_HWID_OWNER_FIELDS = (
    ("user_uuid", "userUuid"),
    ("user_id", "userId"),
)


def _apply_hwid_webhook_compatibility() -> bool:
    """Allow the signed wrapper user to own an HWID event device."""

    known_fields = 0
    patched = False
    for field_name, expected_alias in _HWID_OWNER_FIELDS:
        field = HwidUserDeviceDto.model_fields.get(field_name)
        if field is None:
            continue

        known_fields += 1
        if field.alias != expected_alias:
            raise RuntimeError(
                f"Unsupported remnapy {HwidUserDeviceDto.__name__}.{field_name} contract"
            )

        annotation = field.annotation
        if annotation is None:
            raise RuntimeError(
                f"Unsupported remnapy {HwidUserDeviceDto.__name__}.{field_name} type"
            )
        if type(None) not in get_args(annotation):
            try:
                field.annotation = cast(Any, annotation | None)
            except TypeError as error:
                raise RuntimeError(
                    f"Unsupported remnapy {HwidUserDeviceDto.__name__}.{field_name} type"
                ) from error
            patched = True
        if field.is_required():
            field.default = None
            patched = True

    if known_fields == 0:
        raise RuntimeError("Unsupported remnapy HWID webhook owner contract")

    if patched:
        HwidUserDeviceDto.model_rebuild(force=True)

    return patched


def apply_remnapy_contract_compatibility() -> None:
    """Apply narrow compatibility fixes for current Remnawave payloads."""

    patched = False
    for model in _HOST_RESPONSE_MODELS:
        field = model.model_fields.get(_XHTTP_FIELD)
        if field is None or field.alias != _XHTTP_ALIAS:
            raise RuntimeError(f"Unsupported remnapy {model.__name__}.{_XHTTP_FIELD} contract")
        if not field.is_required():
            continue

        field.default = None
        model.model_rebuild(force=True)
        patched = True

    # The list response embeds HostResponseDto's compiled validator and must be
    # rebuilt after the item model changes.
    if patched:
        GetAllHostsResponseDto.model_rebuild(force=True)
        logger.info("Applied remnapy compatibility for optional host xhttpExtraParams")

    if _apply_hwid_webhook_compatibility():
        logger.info("Applied remnapy compatibility for optional HWID webhook owner fields")

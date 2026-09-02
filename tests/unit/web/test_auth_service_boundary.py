import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from src.core.config import AppConfig
from src.web.dependencies import validate_auth_service_key
from src.web.endpoints.public.auth import router


def config_with_key(value: str | None) -> AppConfig:
    return AppConfig.model_construct(
        auth_service_key=SecretStr(value) if value is not None else None,
    )


def test_auth_router_requires_service_identity_before_every_use_case() -> None:
    assert router.routes
    assert all(route.dependencies for route in router.routes)

    with pytest.raises(HTTPException) as missing:
        validate_auth_service_key(config_with_key("dedicated-secret"), None)
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as invalid:
        validate_auth_service_key(config_with_key("dedicated-secret"), "wrong-secret")
    assert invalid.value.status_code == 401

    validate_auth_service_key(config_with_key("dedicated-secret"), "dedicated-secret")


def test_unconfigured_auth_boundary_fails_closed() -> None:
    with pytest.raises(HTTPException) as unavailable:
        validate_auth_service_key(config_with_key(None), "any-secret")
    assert unavailable.value.status_code == 503

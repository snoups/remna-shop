import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.web.endpoints.public.auth import router
from src.web.schemas import (
    NotificationPreferencesResponse,
    UpdateNotificationPreferencesRequest,
)


def test_notification_preferences_api_is_authenticated_and_not_a_send_endpoint() -> None:
    routes = [route for route in router.routes if isinstance(route, APIRoute)]
    get_route = next(
        route
        for route in routes
        if route.path == "/auth/notification-preferences" and route.methods == {"GET"}
    )
    assert get_route.methods == {"GET"}
    assert get_route.dependencies

    patch_route = next(
        route
        for route in routes
        if route.path == "/auth/notification-preferences"
        and route.methods == {"PATCH"}
    )
    assert patch_route.dependencies
    assert all("send-email" not in route.path for route in routes)


def test_notification_preferences_response_contract() -> None:
    response = NotificationPreferencesResponse(
        subscription_expiration_email_enabled=False,
        email_eligible=True,
        sender_email="notice@example.org",
        days_before=[7, 3, 1],
    )

    assert response.model_dump() == {
        "subscription_expiration_email_enabled": False,
        "email_eligible": True,
        "sender_email": "notice@example.org",
        "days_before": [7, 3, 1],
    }


def test_notification_opt_in_requires_an_explicit_json_boolean() -> None:
    with pytest.raises(ValidationError):
        UpdateNotificationPreferencesRequest(
            subscription_expiration_email_enabled="true",  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError):
        UpdateNotificationPreferencesRequest(
            subscription_expiration_email_enabled=1,  # type: ignore[arg-type]
        )


def test_notification_preferences_path_has_a_side_effect_free_rollout_probe() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/public")

    # Clean Pay probes the exact path with an unsupported method before it has
    # a user session. FastAPI must distinguish the present route (405) from an
    # older image where the path is absent (404), without invoking a use case.
    response = TestClient(app).post(
        "/api/v1/public/auth/notification-preferences",
        json={},
    )

    assert response.status_code == 405

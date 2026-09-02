import base64
import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import SecretStr

from src.application.services.payment_cursor import (
    InvalidPaymentCursorError,
    PaymentCursorCodec,
)
from src.core.config import AppConfig

JWT_SECRET = "test-only-jwt-secret-with-at-least-32-bytes"
INVALID_CURSOR_MESSAGE = "Invalid payment cursor"


def make_codec(secret: str = JWT_SECRET) -> PaymentCursorCodec:
    config = AppConfig.model_construct(jwt_secret=SecretStr(secret))
    return PaymentCursorCodec(config)


def make_signed_cursor(codec: PaymentCursorCodec, payload_bytes: bytes) -> str:
    envelope = payload_bytes + codec._sign(payload_bytes)
    return base64.urlsafe_b64encode(envelope).rstrip(b"=").decode("ascii")


def make_signed_payload(codec: PaymentCursorCodec, payload: object) -> str:
    payload_bytes = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return make_signed_cursor(codec, payload_bytes)


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "c": "2026-07-17T20:31:42.123456+00:00",
        "i": 99,
        "u": 7,
        "v": 1,
    }
    payload.update(overrides)
    return payload


def assert_invalid(codec: PaymentCursorCodec, cursor: object, expected_user_id: object = 7) -> None:
    with pytest.raises(InvalidPaymentCursorError) as error:
        codec.decode(cursor, expected_user_id=expected_user_id)  # type: ignore[arg-type]
    assert str(error.value) == INVALID_CURSOR_MESSAGE
    assert error.value.__cause__ is None


def test_round_trip_is_deterministic_and_preserves_exact_instant() -> None:
    codec = make_codec()
    created_at = datetime(
        2026,
        7,
        17,
        23,
        31,
        42,
        123456,
        tzinfo=timezone(timedelta(hours=3)),
    )

    first = codec.encode(user_id=7, created_at=created_at, transaction_id=99)
    second = codec.encode(user_id=7, created_at=created_at, transaction_id=99)
    equivalent_utc = codec.encode(
        user_id=7,
        created_at=created_at.astimezone(UTC),
        transaction_id=99,
    )

    assert first == second == equivalent_utc
    assert first.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_") == ""
    assert "=" not in first
    decoded = codec.decode(first, expected_user_id=7)
    assert decoded.user_id == 7
    assert decoded.created_at == created_at
    assert decoded.created_at.tzinfo is UTC
    assert decoded.created_at.microsecond == 123456
    assert decoded.transaction_id == 99


def test_different_secrets_produce_different_cursors_and_cannot_verify_each_other() -> None:
    first_codec = make_codec("a" * 32)
    second_codec = make_codec("b" * 32)
    created_at = datetime(2026, 7, 17, tzinfo=UTC)

    first = first_codec.encode(user_id=7, created_at=created_at, transaction_id=99)
    second = second_codec.encode(user_id=7, created_at=created_at, transaction_id=99)

    assert first != second
    assert_invalid(second_codec, first)


def test_cross_user_cursor_is_rejected_with_safe_error() -> None:
    codec = make_codec()
    cursor = codec.encode(
        user_id=7,
        created_at=datetime(2026, 7, 17, tzinfo=UTC),
        transaction_id=99,
    )

    assert_invalid(codec, cursor, expected_user_id=8)


def test_single_character_tampering_is_rejected() -> None:
    codec = make_codec()
    cursor = codec.encode(
        user_id=7,
        created_at=datetime(2026, 7, 17, tzinfo=UTC),
        transaction_id=99,
    )
    replacement = "A" if cursor[-1] != "A" else "B"

    assert_invalid(codec, cursor[:-1] + replacement)


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "not+a+base64url+cursor",
        "abc=",
        "a",
        "a" * 513,
        123,
        None,
    ],
)
def test_malformed_envelopes_are_rejected(cursor: object) -> None:
    assert_invalid(make_codec(), cursor)


@pytest.mark.parametrize(
    "payload",
    [
        {"c": "2026-07-17T20:31:42.123456+00:00", "i": 99, "u": 7},
        valid_payload(extra="field"),
        valid_payload(v=2),
        valid_payload(v=True),
        valid_payload(u="7"),
        valid_payload(u=True),
        valid_payload(u=0),
        valid_payload(u=2_147_483_648),
        valid_payload(i="99"),
        valid_payload(i=True),
        valid_payload(i=0),
        valid_payload(i=2_147_483_648),
        valid_payload(c=123),
        valid_payload(c="2026-07-17T20:31:42.123456"),
        valid_payload(c="2026-07-17T23:31:42.123456+03:00"),
        valid_payload(c="2026-07-17T20:31:42.123456Z"),
        valid_payload(c="2026-07-17T20:31:42+00:00"),
        [1, 2, 3],
    ],
)
def test_validly_signed_noncanonical_payloads_are_rejected(payload: object) -> None:
    codec = make_codec()
    assert_invalid(codec, make_signed_payload(codec, payload))


def test_duplicate_json_keys_are_rejected() -> None:
    codec = make_codec()
    duplicate = b'{"c":"2026-07-17T20:31:42.123456+00:00","i":99,"u":7,"u":8,"v":1}'

    assert_invalid(codec, make_signed_cursor(codec, duplicate))


@pytest.mark.parametrize("payload", [b"not-json", b"\xff", b""])
def test_validly_signed_malformed_payloads_are_rejected(payload: bytes) -> None:
    codec = make_codec()
    assert_invalid(codec, make_signed_cursor(codec, payload))


@pytest.mark.parametrize("value", [0, -1, 2_147_483_648, True, "7", None])
def test_encode_rejects_invalid_user_ids(value: object) -> None:
    with pytest.raises(ValueError):
        make_codec().encode(
            user_id=value,  # type: ignore[arg-type]
            created_at=datetime(2026, 7, 17, tzinfo=UTC),
            transaction_id=99,
        )


@pytest.mark.parametrize("value", [0, -1, 2_147_483_648, True, "99", None])
def test_encode_rejects_invalid_transaction_ids(value: object) -> None:
    with pytest.raises(ValueError):
        make_codec().encode(
            user_id=7,
            created_at=datetime(2026, 7, 17, tzinfo=UTC),
            transaction_id=value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 7, 17, tzinfo=UTC).replace(tzinfo=None),
        "2026-07-17T00:00:00+00:00",
        None,
    ],
)
def test_encode_rejects_non_aware_datetimes(value: object) -> None:
    with pytest.raises(ValueError):
        make_codec().encode(
            user_id=7,
            created_at=value,  # type: ignore[arg-type]
            transaction_id=99,
        )


@pytest.mark.parametrize("expected_user_id", [0, -1, 2_147_483_648, True, "7", None])
def test_decode_rejects_invalid_expected_user_id(expected_user_id: object) -> None:
    codec = make_codec()
    cursor = codec.encode(
        user_id=7,
        created_at=datetime(2026, 7, 17, tzinfo=UTC),
        transaction_id=99,
    )

    assert_invalid(codec, cursor, expected_user_id)


@pytest.mark.parametrize("secret", [None, SecretStr("")])
def test_codec_requires_configured_app_jwt_secret(secret: SecretStr | None) -> None:
    config = AppConfig.model_construct(jwt_secret=secret)

    with pytest.raises(ValueError, match="APP_JWT_SECRET is required"):
        PaymentCursorCodec(config)

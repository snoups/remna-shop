import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

from src.core.config import AppConfig

_CURSOR_VERSION: Final = 1
_HMAC_SIZE: Final = hashlib.sha256().digest_size
_KEY_DOMAIN: Final = b"remnashop/payment-transaction-cursor/key/v1"
_SIGNATURE_DOMAIN: Final = b"remnashop/payment-transaction-cursor/payload/v1\x00"
_MAX_CURSOR_LENGTH: Final = 512
_MAX_PAYLOAD_LENGTH: Final = 256
_MIN_DATABASE_ID: Final = 1
_MAX_DATABASE_ID: Final = 2_147_483_647
_PAYLOAD_KEYS: Final = frozenset({"v", "u", "c", "i"})
_INVALID_CURSOR_MESSAGE: Final = "Invalid payment cursor"


class InvalidPaymentCursorError(ValueError):
    """A client-safe error for every rejected payment cursor."""

    def __init__(self) -> None:
        super().__init__(_INVALID_CURSOR_MESSAGE)


@dataclass(frozen=True, slots=True)
class PaymentCursor:
    user_id: int
    created_at: datetime
    transaction_id: int


class PaymentCursorCodec:
    """Encode and authenticate keyset-pagination cursors for payment history."""

    def __init__(self, config: AppConfig) -> None:
        jwt_secret = config.jwt_secret
        if jwt_secret is None or not jwt_secret.get_secret_value():
            raise ValueError("APP_JWT_SECRET is required for payment cursors")

        # Keep only a purpose-specific derived key, not the reusable JWT secret.
        self._signing_key = hmac.new(
            jwt_secret.get_secret_value().encode("utf-8"),
            _KEY_DOMAIN,
            hashlib.sha256,
        ).digest()

    def encode(self, *, user_id: int, created_at: datetime, transaction_id: int) -> str:
        normalized_user_id = _validate_database_id(user_id, "user_id")
        normalized_transaction_id = _validate_database_id(transaction_id, "transaction_id")
        normalized_created_at = _normalize_datetime(created_at)

        payload = {
            "c": normalized_created_at.isoformat(timespec="microseconds"),
            "i": normalized_transaction_id,
            "u": normalized_user_id,
            "v": _CURSOR_VERSION,
        }
        payload_bytes = json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        signature = self._sign(payload_bytes)
        return _b64url_encode(payload_bytes + signature)

    def decode(self, cursor: str, *, expected_user_id: int) -> PaymentCursor:
        try:
            normalized_expected_user_id = _validate_database_id(
                expected_user_id,
                "expected_user_id",
            )
            payload_bytes, supplied_signature = _decode_envelope(cursor)
            expected_signature = self._sign(payload_bytes)
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise InvalidPaymentCursorError

            payload = _decode_payload(payload_bytes)
            version = payload["v"]
            user_id = payload["u"]
            created_at = payload["c"]
            transaction_id = payload["i"]

            if type(version) is not int or version != _CURSOR_VERSION:
                raise InvalidPaymentCursorError
            if type(user_id) is not int:
                raise InvalidPaymentCursorError
            if type(transaction_id) is not int:
                raise InvalidPaymentCursorError
            if type(created_at) is not str:
                raise InvalidPaymentCursorError

            decoded_user_id = _validate_database_id(user_id, "user_id")
            decoded_transaction_id = _validate_database_id(transaction_id, "transaction_id")
            decoded_created_at = _decode_datetime(created_at)
            if decoded_user_id != normalized_expected_user_id:
                raise InvalidPaymentCursorError

            return PaymentCursor(
                user_id=decoded_user_id,
                created_at=decoded_created_at,
                transaction_id=decoded_transaction_id,
            )
        except InvalidPaymentCursorError:
            raise
        except (UnicodeError, ValueError, TypeError, OverflowError):
            raise InvalidPaymentCursorError from None

    def _sign(self, payload: bytes) -> bytes:
        return hmac.new(
            self._signing_key,
            _SIGNATURE_DOMAIN + payload,
            hashlib.sha256,
        ).digest()


def _validate_database_id(value: object, field: str) -> int:
    if type(value) is not int or not _MIN_DATABASE_ID <= value <= _MAX_DATABASE_ID:
        raise ValueError(f"{field} must be a positive signed 32-bit integer")
    return value


def _normalize_datetime(value: object) -> datetime:
    if type(value) is not datetime:
        raise ValueError("created_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError("created_at is outside the supported range") from error


def _decode_datetime(value: str) -> datetime:
    # A single canonical representation prevents multiple signed encodings of one key.
    if len(value) != 32:
        raise InvalidPaymentCursorError
    try:
        decoded = datetime.fromisoformat(value)
    except ValueError:
        raise InvalidPaymentCursorError from None
    if decoded.tzinfo is None or decoded.utcoffset() != timedelta(0):
        raise InvalidPaymentCursorError
    normalized = decoded.astimezone(UTC)
    if normalized.isoformat(timespec="microseconds") != value:
        raise InvalidPaymentCursorError
    return normalized


def _decode_envelope(cursor: object) -> tuple[bytes, bytes]:
    if type(cursor) is not str or not cursor or len(cursor) > _MAX_CURSOR_LENGTH:
        raise InvalidPaymentCursorError
    if any(
        not (character.isascii() and (character.isalnum() or character in "-_"))
        for character in cursor
    ):
        raise InvalidPaymentCursorError

    encoded = cursor.encode("ascii")
    padding = b"=" * (-len(encoded) % 4)
    try:
        envelope = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise InvalidPaymentCursorError from None
    if _b64url_encode(envelope) != cursor:
        raise InvalidPaymentCursorError
    if not _HMAC_SIZE < len(envelope) <= _HMAC_SIZE + _MAX_PAYLOAD_LENGTH:
        raise InvalidPaymentCursorError
    return envelope[:-_HMAC_SIZE], envelope[-_HMAC_SIZE:]


def _decode_payload(payload_bytes: bytes) -> dict[str, object]:
    try:
        decoded: object = json.loads(
            payload_bytes.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise InvalidPaymentCursorError from None
    if type(decoded) is not dict:
        raise InvalidPaymentCursorError
    payload = cast(dict[str, object], decoded)
    if frozenset(payload) != _PAYLOAD_KEYS:
        raise InvalidPaymentCursorError
    return payload


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

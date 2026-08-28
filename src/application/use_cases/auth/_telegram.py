import hashlib
import hmac
import time
from typing import Any
from urllib.parse import parse_qsl

from src.core.constants import AUTH_TELEGRAM_MAX_AGE_SECONDS


def verify_telegram_auth(data: dict[str, Any], bot_token: str) -> bool:
    telegram_hash = str(data.get("hash", ""))
    auth_date = int(data.get("auth_date", 0))

    if int(time.time()) - auth_date > AUTH_TELEGRAM_MAX_AGE_SECONDS:
        return False

    data_check = {k: str(v) for k, v in data.items() if k != "hash"}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data_check.items()))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, telegram_hash)


def parse_webapp_init_data(init_data: str) -> dict[str, str]:
    return dict(parse_qsl(init_data, keep_blank_values=True))


def verify_telegram_webapp_init_data(init_data: str, bot_token: str) -> bool:
    fields = parse_webapp_init_data(init_data)
    telegram_hash = fields.pop("hash", "")
    if not telegram_hash:
        return False

    auth_date = int(fields.get("auth_date", 0))
    if int(time.time()) - auth_date > AUTH_TELEGRAM_MAX_AGE_SECONDS:
        return False

    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, telegram_hash)

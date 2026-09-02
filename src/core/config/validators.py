from typing import Any

from pydantic import SecretStr, ValidationInfo

from src.core.utils.validators import is_valid_username


def validate_not_change_me(value: Any, info: ValidationInfo) -> Any:
    current_value = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
    env_prefix = info.config.get("env_prefix", "") if info.config else ""
    field_name = info.field_name.upper() if info.field_name else "UNKNOWN_FIELD"
    full_env_var_name = f"{env_prefix}{field_name}"

    if not current_value or current_value.strip().lower() == "change_me":
        raise ValueError(f"{full_env_var_name} must be set and not equal to 'change_me'")

    return value


def validate_username(value: Any, info: ValidationInfo) -> Any:
    current_value = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
    env_prefix = info.config.get("env_prefix", "") if info.config else ""
    field_name = info.field_name.upper() if info.field_name else "UNKNOWN_FIELD"
    full_env_var_name = f"{env_prefix}{field_name}"

    if not is_valid_username(f"@{current_value}"):
        raise ValueError(f"{full_env_var_name} contains invalid Telegram username")

    return value

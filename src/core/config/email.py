from typing import Self
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator, model_validator

from src.core.utils.validators import is_valid_url

from .base import BaseConfig


class EmailConfig(BaseConfig, env_prefix="EMAIL_"):
    enabled: bool = False
    # Independent, fail-closed kill switch for scheduled subscription reminders.
    # SMTP can remain enabled for verification and password-reset messages while
    # reminders are disabled globally.
    subscription_expiration_reminders_enabled: bool = False
    subscription_expiration_cabinet_url: str = ""

    host: str = ""
    port: int = 587
    use_tls: bool = True
    use_ssl: bool = False
    # Development-only escape hatch for local SMTP sinks. Never enable for a
    # remote or production SMTP server: credentials and messages are plaintext.
    allow_insecure_smtp: bool = False

    username: SecretStr = SecretStr("")
    password: SecretStr = SecretStr("")

    from_email: str = ""
    from_name: str = ""

    verification_code_ttl_minutes: int = 15

    @model_validator(mode="after")
    def validate_smtp_transport_security(self) -> Self:
        if self.use_tls and self.use_ssl:
            raise ValueError("EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be true")
        if (
            self.enabled
            and not self.use_tls
            and not self.use_ssl
            and not self.allow_insecure_smtp
        ):
            raise ValueError(
                "Enabled SMTP requires EMAIL_USE_TLS=true or EMAIL_USE_SSL=true; "
                "plaintext is development-only and requires explicit "
                "EMAIL_ALLOW_INSECURE_SMTP=true"
            )
        return self

    @field_validator("subscription_expiration_cabinet_url")
    @classmethod
    def validate_subscription_expiration_cabinet_url(cls, value: str) -> str:
        url = value.strip()
        if not url:
            return url
        try:
            parsed = urlsplit(url)
            # Access validates malformed/out-of-range ports as well.
            _ = parsed.port
        except ValueError as exc:
            raise ValueError(
                "EMAIL_SUBSCRIPTION_EXPIRATION_CABINET_URL must be an HTTPS URL "
                "with a hostname and without userinfo"
            ) from exc
        if (
            not is_valid_url(url)
            or parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "EMAIL_SUBSCRIPTION_EXPIRATION_CABINET_URL must be an HTTPS URL "
                "with a hostname and without userinfo"
            )
        return url

from pydantic import Field, SecretStr, model_validator

from .base import BaseConfig


class OutboundWebhookConfig(BaseConfig, env_prefix="WEBHOOK_"):
    enabled: bool = False

    url: str = ""
    secret: SecretStr = SecretStr("")
    timeout: float = 15.0

    # Total delivery attempts (including the first one) and base delay between
    # them; the broker applies exponential backoff with jitter on top.
    retries: int = Field(default=5, ge=1)
    retry_delay: float = Field(default=15.0, gt=0)

    @model_validator(mode="after")
    def validate_webhook_settings(self) -> "OutboundWebhookConfig":
        if self.enabled:
            if not self.url.startswith(("http://", "https://")):
                raise ValueError(
                    "WEBHOOK_URL must be a valid http(s) URL when WEBHOOK_ENABLED=true"
                )
            if not self.secret.get_secret_value():
                raise ValueError("WEBHOOK_SECRET must be set when WEBHOOK_ENABLED=true")
        return self

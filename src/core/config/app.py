import re
from pathlib import Path
from typing import Optional, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_core.core_schema import FieldValidationInfo

from src.core.constants import API_V1, ASSETS_DEFAULT_DIR, ASSETS_DIR, PAYMENTS_WEBHOOK_PATH
from src.core.enums import Locale, PaymentGatewayType
from src.core.types import LocaleList, StringList
from src.core.utils.validators import is_valid_domain, is_valid_url

from .base import BaseConfig
from .bot import BotConfig
from .build import BuildConfig
from .database import DatabaseConfig
from .email import EmailConfig
from .log import LogConfig
from .redis import RedisConfig
from .remnawave import RemnawaveConfig
from .validators import validate_not_change_me


class AppConfig(BaseConfig, env_prefix="APP_"):
    domain: SecretStr
    host: str = "0.0.0.0"
    port: int = 5000

    locales: LocaleList = LocaleList([Locale.RU])  # TODO: Change to EN
    default_locale: Locale = Locale.RU  # TODO: Change to EN

    crypt_key: SecretStr
    jwt_secret: Optional[SecretStr] = None
    api_key: Optional[SecretStr] = None
    assets_dir: Path = ASSETS_DIR
    origins: StringList = StringList("")
    swagger_enabled: bool = False
    web_enabled: bool = Field(default=False, validation_alias="WEB_ENABLED")
    web_cabinet_url: str = Field(default="", validation_alias="WEB_CABINET_URL")

    bot: BotConfig = Field(default_factory=BotConfig)
    remnawave: RemnawaveConfig = Field(default_factory=RemnawaveConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    build: BuildConfig = Field(default_factory=BuildConfig)
    log: LogConfig = Field(default_factory=LogConfig)

    @property
    def default_assets_dir(self) -> Path:
        return ASSETS_DEFAULT_DIR

    @property
    def banners_dir(self) -> Path:
        return self.assets_dir / "banners"

    @property
    def translations_dir(self) -> Path:
        return self.assets_dir / "translations"

    @property
    def default_banners_dir(self) -> Path:
        return self.default_assets_dir / "banners"

    @property
    def default_translations_dir(self) -> Path:
        return self.default_assets_dir / "translations"

    def get_webhook(self, gateway_type: PaymentGatewayType) -> str:
        domain = f"https://{self.domain.get_secret_value()}"
        path = f"{API_V1 + PAYMENTS_WEBHOOK_PATH}/{gateway_type.lower()}"
        return domain + path

    @classmethod
    def get(cls) -> Self:
        return cls()

    @model_validator(mode="after")
    def validate_web_secrets(self) -> "AppConfig":
        if self.web_enabled:
            if not self.api_key:
                raise ValueError(
                    "APP_API_KEY must be set when WEB_ENABLED=true; "
                    "do not reuse APP_CRYPT_KEY for API authentication"
                )
            if not self.jwt_secret:
                raise ValueError(
                    "APP_JWT_SECRET must be set when WEB_ENABLED=true; "
                    "do not reuse APP_CRYPT_KEY for JWT signing"
                )
        return self

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        validate_not_change_me(field, info)

        if not is_valid_domain(field.get_secret_value()):
            raise ValueError("APP_DOMAIN has invalid format")

        return field

    @field_validator("web_cabinet_url")
    @classmethod
    def validate_web_cabinet_url(cls, value: str) -> str:
        url = value.strip()
        if url and not is_valid_url(url):
            raise ValueError("WEB_CABINET_URL must be an HTTPS URL")
        return url

    @field_validator("crypt_key")
    @classmethod
    def validate_crypt_key(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        validate_not_change_me(field, info)

        if not re.match(r"^[A-Za-z0-9+/=]{44}$", field.get_secret_value()):
            raise ValueError("APP_CRYPT_KEY must be a valid 44-character Base64 string")

        return field

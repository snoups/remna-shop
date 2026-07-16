import re
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from re import Pattern
from typing import Final

from packaging.version import Version

from src.core.enums import Currency

BASE_DIR: Final[Path] = Path(__file__).resolve().parents[2]
ASSETS_DIR: Final[Path] = BASE_DIR / "assets"
ASSETS_DEFAULT_DIR: Final[Path] = BASE_DIR / "assets.default"
BACKUP_DIR: Final[Path] = BASE_DIR / "backups"
LOG_DIR: Final[Path] = BASE_DIR / "logs"

# Per-currency default price for a freshly added plan duration (mirrors the
# configurator's 30-day tier). Avoids the absurd USD=100 shared default.
DEFAULT_DURATION_PRICES: Final[dict[Currency, Decimal]] = {
    Currency.USD: Decimal("1"),
    Currency.XTR: Decimal("60"),
    Currency.RUB: Decimal("100"),
}

DOMAIN_REGEX: Pattern[str] = re.compile(r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$")
TAG_REGEX: Pattern[str] = re.compile(r"^[A-Z0-9_]{1,16}$")
URL_PATTERN: Pattern[str] = re.compile(r"^https://\S+$")
USERNAME_PATTERN: Pattern[str] = re.compile(r"^@[a-zA-Z0-9_]{5,32}$")
INVITE_LINK_PATTERN: Pattern[str] = re.compile(r"^https://t\.me/(\+|joinchat/)[A-Za-z0-9_\-]+")

REMNAWAVE_MIN_VERSION: Final[Version] = Version("2.7.0")
REMNAWAVE_MAX_VERSION: Final[Version] = Version("2.8.0")

REPOSITORY: Final[str] = "https://github.com/snoups/remnashop"
DOCS: Final[str] = "https://remnashop.mintlify.app"
T_ME: Final[str] = "https://t.me/"
API_V1: Final[str] = "/api/v1"
BOT_WEBHOOK_PATH: Final[str] = "/telegram"
PAYMENTS_WEBHOOK_PATH: Final[str] = "/payments"
REMNAWAVE_WEBHOOK_PATH: Final[str] = "/remnawave"
UNITPAY_PAY_PATH: Final[str] = "/pay/unitpay"

IMPORTED_TAG: Final[str] = "IMPORTED"
INLINE_QUERY_INVITE: Final[str] = "invite"
REMNASHOP_PREFIX: Final[str] = "rs_"
WEB_PREFIX: Final[str] = "web_"
PAYMENT_PREFIX: Final[str] = "payment_"
GOTO_PREFIX: Final[str] = "gt_"
ENCRYPTED_PREFIX: Final[str] = "enc_"

MIDDLEWARE_DATA_KEY: Final[str] = "middleware_data"
CONTAINER_KEY: Final[str] = "dishka_container"
CONFIG_KEY: Final[str] = "config"
USER_KEY: Final[str] = "user"
TARGET_TELEGRAM_ID: Final[str] = "target_telegram_id"
TARGET_USER_ID: Final[str] = "target_user_id"
FROM_REFERRAL_USER_ID: Final[str] = "from_referral_user_id"
USER_LIST_ORIGIN: Final[str] = "user_list_origin"
USER_LIST_PAYLOAD: Final[str] = "user_list_payload"

INT32_MAX: Final[int] = 2_147_483_647

TIMEZONE: Final[timezone] = timezone.utc
DATETIME_VIEW_FORMAT: Final[str] = "%d.%m.%y %H:%M:%S"
DATETIME_FILE_FORMAT: Final[str] = "%Y-%m-%d_%H-%M-%S"

TIME_1M: Final[int] = 60
TIME_1H: Final[int] = TIME_1M * 60
TIME_1D: Final[int] = TIME_1H * 24

TTL_5M: Final[int] = TIME_1M * 5
TTL_10M: Final[int] = TIME_1M * 10
TTL_30M: Final[int] = TIME_1M * 30
TTL_1H: Final[int] = TIME_1H
TTL_6H: Final[int] = TIME_1H * 6
TTL_12H: Final[int] = TIME_1H * 12
TTL_1D: Final[int] = TIME_1D
TTL_7D: Final[int] = TIME_1D * 7

RECENT_REGISTERED_MAX_COUNT: Final[int] = 50
RECENT_ACTIVITY_MAX_COUNT: Final[int] = 50
RECENT_ACTIVITY_STORE_CAP: Final[int] = 200

UNLIMITED_EXPIRE_YEAR: Final[int] = 2099

BATCH_SIZE_10: Final[int] = 10
BATCH_SIZE_20: Final[int] = 20
BATCH_DELAY: Final[int] = 1

TEXT_MAX_LENGTH: Final[int] = 4096
TEXT_MEDIA_MAX_LENGTH: Final[int] = 1024

PASSWORD_SCRYPT_N: Final[int] = 2**14
PASSWORD_SCRYPT_R: Final[int] = 8
PASSWORD_SCRYPT_P: Final[int] = 1
PASSWORD_SCRYPT_DKLEN: Final[int] = 64
ACCESS_TOKEN_TTL_SECONDS: Final[int] = 900  # 15 minutes
REFRESH_TOKEN_TTL_SECONDS: Final[int] = 60 * 60 * 24 * 30  # 30 days
TELEGRAM_AUTH_MAX_AGE_SECONDS: Final[int] = 600  # 10 minutes
PUBLIC_LANDING_PLANS_CACHE_TTL_SECONDS: Final[int] = 21600
EMAIL_VERIFICATION_CODE_LENGTH: Final[int] = 6
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS: Final[int] = 60
EMAIL_VERIFICATION_SUBJECT: Final[str] = "Your verification code"
EMAIL_VERIFICATION_BODY_TEMPLATE: Final[str] = (
    "Your verification code is: {code}\n\n"
    "It is valid for {minutes} minutes. If you did not request this, ignore this email."
)
WEB_PASSWORD_LEN: Final[int] = 8
WEB_PASSWORD_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

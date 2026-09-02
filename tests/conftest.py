import base64
import os

# Importing the endpoint package initializes the task broker, whose configuration
# validates the bot section eagerly. Unit tests use non-secret placeholders and
# never start the broker or make network calls.
os.environ.setdefault("BOT_TOKEN", "unit-test-token")
os.environ.setdefault("BOT_SECRET_TOKEN", "unit-test-secret")
os.environ.setdefault("BOT_OWNER_ID", "1")
os.environ.setdefault("BOT_SUPPORT_USERNAME", "unit_test_support")
os.environ.setdefault("REMNAWAVE_TOKEN", "unit-test-remnawave-token")
os.environ.setdefault("REMNAWAVE_WEBHOOK_SECRET", "unit-test-webhook-secret")
os.environ.setdefault("DATABASE_PASSWORD", "unit-test-database-password")
os.environ.setdefault("APP_DOMAIN", "example.com")
os.environ.setdefault(
    "APP_CRYPT_KEY",
    base64.urlsafe_b64encode(b"0" * 32).decode(),
)

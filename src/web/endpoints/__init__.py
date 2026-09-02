from .admin import router as admin_router
from .health import router as health_router
from .payments import router as payments_router
from .public import router as public_router
from .remnawave import router as remnawave_router
from .telegram import TelegramWebhookEndpoint

__all__ = [
    "admin_router",
    "health_router",
    "payments_router",
    "public_router",
    "remnawave_router",
    "TelegramWebhookEndpoint",
]

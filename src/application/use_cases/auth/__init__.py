from typing import Final

from src.application.common import Interactor

from .commands.email import (
    ChangeEmail,
    ConfirmEmailVerification,
    RequestEmailVerification,
)
from .commands.login import LoginEmailUser
from .commands.password import ChangePassword, ConfirmPasswordReset, RequestPasswordReset
from .commands.register import RegisterEmailUser
from .commands.session import RefreshSession
from .commands.telegram import AuthenticateTelegram, AuthenticateTelegramWebApp, LinkTelegram

AUTH_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    RegisterEmailUser,
    LoginEmailUser,
    RefreshSession,
    AuthenticateTelegram,
    AuthenticateTelegramWebApp,
    LinkTelegram,
    ChangePassword,
    RequestPasswordReset,
    ConfirmPasswordReset,
    ChangeEmail,
    RequestEmailVerification,
    ConfirmEmailVerification,
)

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import HTTPException, status
from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import UserDao
from src.application.common.dao.auth import AuthSessionDao
from src.application.common.email_sender import EmailSender
from src.application.common.password_hasher import PasswordHasher
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.use_cases.auth._codes import (
    generate_email_verification_code,
    hash_email_verification_code,
)
from src.application.use_cases.auth.commands.register import (
    RegisterEmailUser,
    RegisterEmailUserDto,
)
from src.core.config import AppConfig
from src.core.constants import (
    EMAIL_CODE_RESEND_COOLDOWN_SECONDS,
    EMAIL_VERIFICATION_BODY_TEMPLATE,
    EMAIL_VERIFICATION_SUBJECT,
)

EMAIL_AUTH_ATTEMPT_LIMIT = 5
EMAIL_AUTH_ATTEMPT_WINDOW_SECONDS = 15 * 60


def email_auth_identity(email: str, secret: str) -> str:
    normalized = email.strip().casefold()
    return hmac.new(
        secret.encode(), f"email-auth:{normalized}".encode(), hashlib.sha256
    ).hexdigest()


@dataclass
class StartGenericEmailAuthDto:
    email: str


@dataclass
class GenericEmailAuthStarted:
    success: bool = True


class StartGenericEmailAuth(Interactor[StartGenericEmailAuthDto, GenericEmailAuthStarted]):
    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        email_sender: EmailSender,
        auth_session: AuthSessionDao,
    ) -> None:
        self.config = config
        self.email_sender = email_sender
        self.auth_session = auth_session

    async def _execute(
        self, actor: UserDto, data: StartGenericEmailAuthDto
    ) -> GenericEmailAuthStarted:
        secret = self.config.crypt_key.get_secret_value()
        identity = email_auth_identity(data.email, secret)

        try:
            reserved = await self.auth_session.reserve_email_auth_request(
                identity, EMAIL_CODE_RESEND_COOLDOWN_SECONDS
            )
        except Exception:
            logger.warning("Generic email auth limiter is unavailable")
            return GenericEmailAuthStarted()

        if not reserved or not self.email_sender.is_enabled:
            return GenericEmailAuthStarted()

        code = generate_email_verification_code()
        ttl = self.config.email.verification_code_ttl_minutes * 60
        code_hash = hash_email_verification_code(code, secret)

        try:
            await self.auth_session.store_email_auth_challenge(identity, code_hash, ttl)
            await self.email_sender.send(
                to=data.email,
                subject=EMAIL_VERIFICATION_SUBJECT,
                body=EMAIL_VERIFICATION_BODY_TEMPLATE.format(
                    code=code,
                    minutes=self.config.email.verification_code_ttl_minutes,
                ),
            )
        except Exception:
            logger.warning("Generic email auth delivery failed")

        return GenericEmailAuthStarted()


@dataclass
class CompleteGenericEmailAuthDto:
    email: str
    code: str
    password: str


class CompleteGenericEmailAuth(Interactor[CompleteGenericEmailAuthDto, UserDto]):
    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        uow: UnitOfWork,
        user_dao: UserDao,
        auth_session: AuthSessionDao,
        password_hasher: PasswordHasher,
        register_email_user: RegisterEmailUser,
    ) -> None:
        self.config = config
        self.uow = uow
        self.user_dao = user_dao
        self.auth_session = auth_session
        self.password_hasher = password_hasher
        self.register_email_user = register_email_user

    async def _execute(self, actor: UserDto, data: CompleteGenericEmailAuthDto) -> UserDto:
        secret = self.config.crypt_key.get_secret_value()
        identity = email_auth_identity(data.email, secret)
        attempts = await self.auth_session.increment_email_auth_attempts(
            identity, EMAIL_AUTH_ATTEMPT_WINDOW_SECONDS
        )
        if attempts > EMAIL_AUTH_ATTEMPT_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many email authentication attempts",
            )

        code_hash = hash_email_verification_code(data.code, secret)
        if not await self.auth_session.consume_email_auth_challenge(identity, code_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification code",
            )

        user = await self.user_dao.get_by_email(data.email)
        if user:
            if user.is_blocked:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")
            if user.password_hash and not self.password_hasher.verify(
                data.password, user.password_hash
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password",
                )
            if not user.password_hash:
                user.password_hash = self.password_hasher.hash(data.password)
            user.is_email_verified = True
            user.pending_email = None
            async with self.uow:
                updated = await self.user_dao.update(user)
                if not updated:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User disappeared during email authentication",
                    )
                await self.uow.commit()
            result = updated
        else:
            result = await self.register_email_user.system(
                RegisterEmailUserDto(email=data.email, password=data.password)
            )
            result.is_email_verified = True
            async with self.uow:
                updated = await self.user_dao.update(result)
                if not updated:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User disappeared during email authentication",
                    )
                await self.uow.commit()
            result = updated

        await self.auth_session.clear_email_auth_attempts(identity)
        return result

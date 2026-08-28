import hmac
from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException, status
from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import UserDao
from src.application.common.dao.auth import AuthSessionDao
from src.application.common.email_sender import EmailSender
from src.application.common.password_hasher import PasswordHasher
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.use_cases.auth._codes import (
    check_email_resend_cooldown,
    generate_email_verification_code,
    hash_email_verification_code,
)
from src.core.config import AppConfig
from src.core.constants import (
    EMAIL_CODE_MAX_ATTEMPTS,
    EMAIL_CODE_RESEND_COOLDOWN_SECONDS,
    EMAIL_PASSWORD_RESET_BODY_TEMPLATE,
    EMAIL_PASSWORD_RESET_SUBJECT,
)
from src.core.utils.time import datetime_now


@dataclass
class ChangePasswordDto:
    current_password: str
    new_password: str


class ChangePassword(Interactor[ChangePasswordDto, UserDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        auth_session: AuthSessionDao,
        password_hasher: PasswordHasher,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.auth_session = auth_session
        self.password_hasher = password_hasher

    async def _execute(self, actor: UserDto, data: ChangePasswordDto) -> UserDto:
        if not self.password_hasher.verify(data.current_password, actor.password_hash or ""):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is invalid",
            )
        if self.password_hasher.verify(data.new_password, actor.password_hash or ""):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="New password must be different from current password",
            )

        actor.password_hash = self.password_hasher.hash(data.new_password)
        actor.token_version += 1

        async with self.uow:
            updated = await self.user_dao.update(actor)
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found during password update",
                )
            await self.uow.commit()

        await self.auth_session.revoke_all_user_tokens(actor.id)
        return updated


@dataclass
class RequestPasswordResetDto:
    email: str


@dataclass
class PasswordResetRequested:
    success: bool = True


class RequestPasswordReset(Interactor[RequestPasswordResetDto, PasswordResetRequested]):
    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        uow: UnitOfWork,
        user_dao: UserDao,
        email_sender: EmailSender,
    ) -> None:
        self.config = config
        self.uow = uow
        self.user_dao = user_dao
        self.email_sender = email_sender

    async def _execute(
        self, actor: UserDto, data: RequestPasswordResetDto
    ) -> PasswordResetRequested:
        user = await self.user_dao.get_by_email(data.email)
        if not user or not user.password_hash or user.is_blocked:
            return PasswordResetRequested()

        if not self.email_sender.is_enabled:
            logger.warning("Password reset requested, but email delivery is disabled")
            return PasswordResetRequested()

        try:
            check_email_resend_cooldown(
                user.password_reset_expires_at,
                self.config.email.verification_code_ttl_minutes,
                EMAIL_CODE_RESEND_COOLDOWN_SECONDS,
                datetime_now(),
            )
        except HTTPException:
            return PasswordResetRequested()

        code = generate_email_verification_code()
        expires_at = datetime_now() + timedelta(
            minutes=self.config.email.verification_code_ttl_minutes
        )

        try:
            await self.email_sender.send(
                to=data.email,
                subject=EMAIL_PASSWORD_RESET_SUBJECT,
                body=EMAIL_PASSWORD_RESET_BODY_TEMPLATE.format(
                    code=code, minutes=self.config.email.verification_code_ttl_minutes
                ),
            )
        except Exception as e:
            logger.warning(f"Password reset email delivery failed: {e}")
            return PasswordResetRequested()

        user.password_reset_code_hash = hash_email_verification_code(
            code, self.config.crypt_key.get_secret_value()
        )
        user.password_reset_expires_at = expires_at
        user.password_reset_attempts = 0

        async with self.uow:
            updated = await self.user_dao.update(user)
            if not updated:
                logger.warning(f"User '{user.id}' disappeared during password reset request")
                return PasswordResetRequested()
            await self.uow.commit()

        return PasswordResetRequested()


@dataclass
class ConfirmPasswordResetDto:
    email: str
    code: str
    new_password: str


class ConfirmPasswordReset(Interactor[ConfirmPasswordResetDto, UserDto]):
    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        uow: UnitOfWork,
        user_dao: UserDao,
        auth_session: AuthSessionDao,
        password_hasher: PasswordHasher,
    ) -> None:
        self.config = config
        self.uow = uow
        self.user_dao = user_dao
        self.auth_session = auth_session
        self.password_hasher = password_hasher

    async def _execute(self, actor: UserDto, data: ConfirmPasswordResetDto) -> UserDto:
        user = await self.user_dao.get_by_email(data.email)
        if not user or not user.password_hash or user.is_blocked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset code",
            )

        if not user.password_reset_code_hash or not user.password_reset_expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password reset was not requested",
            )
        if user.password_reset_expires_at < datetime_now():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Password reset code has expired",
            )

        incoming_hash = hash_email_verification_code(
            data.code, self.config.crypt_key.get_secret_value()
        )
        if not hmac.compare_digest(incoming_hash, user.password_reset_code_hash):
            await self._register_failed_attempt(user)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset code",
            )

        if self.password_hasher.verify(data.new_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="New password must be different from current password",
            )

        user.password_hash = self.password_hasher.hash(data.new_password)
        user.password_reset_code_hash = None
        user.password_reset_expires_at = None
        user.password_reset_attempts = 0
        user.token_version += 1

        async with self.uow:
            updated = await self.user_dao.update(user)
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found during password reset",
                )
            await self.uow.commit()

        await self.auth_session.revoke_all_user_tokens(user.id)
        return updated

    async def _register_failed_attempt(self, user: UserDto) -> None:
        """Count a wrong code and burn the code once the attempt budget is spent.

        A 6-digit code is only 10^6 wide, so without a cap it could be exhausted well
        inside its TTL. After EMAIL_CODE_MAX_ATTEMPTS the user must request a new one.
        """
        user.password_reset_attempts += 1
        exhausted = user.password_reset_attempts >= EMAIL_CODE_MAX_ATTEMPTS

        if exhausted:
            user.password_reset_code_hash = None
            user.password_reset_expires_at = None
            logger.warning(f"Password reset code invalidated for user '{user.id}': too many tries")

        async with self.uow:
            await self.user_dao.update(user)
            await self.uow.commit()

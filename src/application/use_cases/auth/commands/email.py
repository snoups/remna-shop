import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status

from src.application.common import Interactor
from src.application.common.dao import UserDao
from src.application.common.email_sender import EmailSender
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
    EMAIL_CODE_RESEND_COOLDOWN_SECONDS,
    EMAIL_VERIFICATION_BODY_TEMPLATE,
    EMAIL_VERIFICATION_SUBJECT,
)
from src.core.exceptions import EmailDeliveryDisabledError
from src.core.utils.time import datetime_now


@dataclass
class ChangeEmailDto:
    email: str


class ChangeEmail(Interactor[ChangeEmailDto, UserDto]):
    required_permission = Permission.PUBLIC

    def __init__(self, uow: UnitOfWork, user_dao: UserDao) -> None:
        self.uow = uow
        self.user_dao = user_dao

    async def _execute(self, actor: UserDto, data: ChangeEmailDto) -> UserDto:
        existing = await self.user_dao.get_by_email(data.email)
        if existing and existing.id != actor.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

        actor.pending_email = data.email
        actor.is_email_verified = False
        actor.email_verification_code_hash = None
        actor.email_verification_expires_at = None

        async with self.uow:
            updated = await self.user_dao.update(actor)
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found during email change",
                )
            await self.uow.commit()
        return updated


@dataclass
class RequestEmailVerificationDto:
    email: Optional[str] = None


@dataclass
class EmailVerificationRequested:
    user: UserDto
    target_email: str
    expires_at: datetime


class RequestEmailVerification(Interactor[RequestEmailVerificationDto, EmailVerificationRequested]):
    required_permission = Permission.PUBLIC

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
        self, actor: UserDto, data: RequestEmailVerificationDto
    ) -> EmailVerificationRequested:
        if not self.email_sender.is_enabled:
            raise EmailDeliveryDisabledError("Email delivery is not configured")

        requested_email = data.email
        if (
            requested_email
            and actor.email
            and actor.is_email_verified
            and requested_email != actor.email
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email change is available only for users without verified email",
            )

        if requested_email and requested_email != actor.email:
            existing = await self.user_dao.get_by_email(requested_email)
            if existing and existing.id != actor.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
                )
            actor.pending_email = requested_email
            actor.is_email_verified = False
        elif requested_email and requested_email == actor.email and actor.is_email_verified:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email is already verified"
            )

        target_email = actor.pending_email or actor.email
        if not target_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required for verification",
            )

        check_email_resend_cooldown(
            actor.email_verification_expires_at,
            self.config.email.verification_code_ttl_minutes,
            EMAIL_CODE_RESEND_COOLDOWN_SECONDS,
            datetime_now(),
        )

        code = generate_email_verification_code()
        expires_at = datetime_now() + timedelta(
            minutes=self.config.email.verification_code_ttl_minutes
        )

        # FIX: send first; persist code/expiry only on success so a failed SMTP
        # delivery does not leave committed state and a started cooldown.
        await self.email_sender.send(
            to=target_email,
            subject=EMAIL_VERIFICATION_SUBJECT,
            body=EMAIL_VERIFICATION_BODY_TEMPLATE.format(
                code=code, minutes=self.config.email.verification_code_ttl_minutes
            ),
        )

        actor.email_verification_code_hash = hash_email_verification_code(
            code, self.config.crypt_key.get_secret_value()
        )
        actor.email_verification_expires_at = expires_at

        async with self.uow:
            updated = await self.user_dao.update(actor)
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found during email verification request",
                )
            await self.uow.commit()

        return EmailVerificationRequested(
            user=updated, target_email=target_email, expires_at=expires_at
        )


@dataclass
class ConfirmEmailVerificationDto:
    code: str


@dataclass
class EmailVerificationConfirmed:
    user: UserDto
    email: str


class ConfirmEmailVerification(Interactor[ConfirmEmailVerificationDto, EmailVerificationConfirmed]):
    required_permission = Permission.PUBLIC

    def __init__(self, config: AppConfig, uow: UnitOfWork, user_dao: UserDao) -> None:
        self.config = config
        self.uow = uow
        self.user_dao = user_dao

    async def _execute(
        self, actor: UserDto, data: ConfirmEmailVerificationDto
    ) -> EmailVerificationConfirmed:
        if not actor.email_verification_code_hash or not actor.email_verification_expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email verification was not requested",
            )
        if actor.email_verification_expires_at < datetime_now():
            raise HTTPException(
                status_code=status.HTTP_410_GONE, detail="Verification code has expired"
            )

        incoming_hash = hash_email_verification_code(
            data.code, self.config.crypt_key.get_secret_value()
        )
        if not hmac.compare_digest(incoming_hash, actor.email_verification_code_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code"
            )

        verified_email = actor.pending_email or actor.email
        if not verified_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No email to confirm"
            )

        if actor.pending_email:
            existing = await self.user_dao.get_by_email(actor.pending_email)
            if existing and existing.id != actor.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
                )
            actor.email = actor.pending_email

        actor.pending_email = None
        actor.is_email_verified = True
        actor.email_verification_code_hash = None
        actor.email_verification_expires_at = None

        async with self.uow:
            updated = await self.user_dao.update(actor)
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found during email confirmation",
                )
            await self.uow.commit()

        return EmailVerificationConfirmed(user=updated, email=verified_email)

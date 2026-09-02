import asyncio
import smtplib
import ssl
from email.message import EmailMessage

from loguru import logger

from src.application.common.email_sender import EmailSender
from src.core.config import AppConfig
from src.core.exceptions import EmailDeliveryError

_SMTP_AUTH_MAX_ATTEMPTS = 2
_SMTP_AUTH_RETRY_DELAY_SECONDS = 0.5


class SmtpEmailSender(EmailSender):
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def is_enabled(self) -> bool:
        email = self._config.email
        return bool(
            email.enabled
            and email.host
            and email.from_email
            and email.username.get_secret_value()
            and email.password.get_secret_value()
        )

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        message_id: str | None = None,
    ) -> None:
        try:
            await self._send_with_auth_retry(
                to=to,
                subject=subject,
                body=body,
                message_id=message_id,
            )
        except Exception as e:
            logger.error(
                "Failed to send email (error_type={error_type})",
                error_type=type(e).__name__,
            )
            raise EmailDeliveryError(
                "Failed to send email. Please try again later."
            ) from e

    async def _send_with_auth_retry(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        message_id: str | None,
    ) -> None:
        for attempt in range(1, _SMTP_AUTH_MAX_ATTEMPTS + 1):
            try:
                await asyncio.to_thread(
                    self._send_sync,
                    to=to,
                    subject=subject,
                    body=body,
                    message_id=message_id,
                )
                return
            except smtplib.SMTPAuthenticationError:
                if attempt == _SMTP_AUTH_MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "SMTP authentication failed on attempt {attempt}; retrying once",
                    attempt=attempt,
                )
                await asyncio.sleep(_SMTP_AUTH_RETRY_DELAY_SECONDS)

    def _send_sync(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        message_id: str | None,
    ) -> None:
        email = self._config.email
        message = EmailMessage()
        message["Subject"] = subject
        from_name = email.from_name.strip()
        from_email = email.from_email.strip()
        message["From"] = f"{from_name} <{from_email}>" if from_name else from_email
        message["To"] = to
        if message_id:
            message["Message-ID"] = message_id
        message.set_content(body)

        smtp_user = email.username.get_secret_value()
        smtp_password = email.password.get_secret_value()
        tls_context = ssl.create_default_context()

        if email.use_ssl:
            with smtplib.SMTP_SSL(
                email.host,
                email.port,
                timeout=20,
                context=tls_context,
            ) as client:
                client.login(smtp_user, smtp_password)
                client.send_message(message)
            return

        with smtplib.SMTP(email.host, email.port, timeout=20) as client:
            client.ehlo()
            if email.use_tls:
                client.starttls(context=tls_context)
                client.ehlo()
            client.login(smtp_user, smtp_password)
            client.send_message(message)

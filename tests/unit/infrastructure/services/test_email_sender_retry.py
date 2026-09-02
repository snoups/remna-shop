import smtplib
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import SecretStr, ValidationError

from src.core.config.email import EmailConfig
from src.core.exceptions import EmailDeliveryError
from src.infrastructure.services.email_sender import SmtpEmailSender


async def _inline_to_thread(function, **kwargs):
    return function(**kwargs)


def _sender() -> SmtpEmailSender:
    return SmtpEmailSender(SimpleNamespace(email=SimpleNamespace()))


def _smtp_config(
    *,
    port: int,
    use_ssl: bool,
    use_tls: bool,
) -> SimpleNamespace:
    return SimpleNamespace(
        email=SimpleNamespace(
            host="smtp.example.org",
            port=port,
            use_ssl=use_ssl,
            use_tls=use_tls,
            from_name="Clean Pay",
            from_email="notice@example.org",
            username=SecretStr("smtp-user"),
            password=SecretStr("smtp-password"),
        )
    )


def test_email_config_rejects_ambiguous_or_implicit_plaintext_smtp() -> None:
    with pytest.raises(ValidationError, match="cannot both be true"):
        EmailConfig(enabled=True, use_tls=True, use_ssl=True)

    with pytest.raises(ValidationError, match="EMAIL_ALLOW_INSECURE_SMTP"):
        EmailConfig(enabled=True, use_tls=False, use_ssl=False)


def test_email_config_plaintext_requires_explicit_dev_only_override() -> None:
    default_config = EmailConfig()
    assert default_config.allow_insecure_smtp is False

    local_sink = EmailConfig(
        enabled=True,
        use_tls=False,
        use_ssl=False,
        allow_insecure_smtp=True,
    )
    assert local_sink.allow_insecure_smtp is True


async def test_transient_smtp_authentication_failure_retries_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _sender()
    sender._send_sync = Mock(
        side_effect=[smtplib.SMTPAuthenticationError(454, b"temporary auth failure"), None]
    )
    sleep = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.services.email_sender.asyncio.to_thread",
        _inline_to_thread,
    )
    monkeypatch.setattr("src.infrastructure.services.email_sender.asyncio.sleep", sleep)

    await sender.send(to="user@example.com", subject="subject", body="body")

    assert sender._send_sync.call_count == 2
    sleep.assert_awaited_once()


def test_smtp_sender_preserves_stable_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[object] = []

    class FakeSmtp:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def ehlo(self) -> None:
            return None

        def starttls(self, *, context: ssl.SSLContext) -> None:
            assert context.verify_mode == ssl.CERT_REQUIRED
            assert context.check_hostname is True
            return None

        def login(self, username: str, password: str) -> None:
            assert (username, password) == ("smtp-user", "smtp-password")

        def send_message(self, message: object) -> None:
            sent.append(message)

    monkeypatch.setattr(
        "src.infrastructure.services.email_sender.smtplib.SMTP",
        FakeSmtp,
    )
    config = SimpleNamespace(
        email=SimpleNamespace(
            host="smtp.example.org",
            port=587,
            use_ssl=False,
            use_tls=True,
            from_name="Clean Pay",
            from_email="notice@example.org",
            username=SecretStr("smtp-user"),
            password=SecretStr("smtp-password"),
        )
    )
    sender = SmtpEmailSender(config)  # type: ignore[arg-type]

    sender._send_sync(
        to="user@example.org",
        subject="subject",
        body="body",
        message_id="<subscription-expiration-42@example.org>",
    )

    assert len(sent) == 1
    message = sent[0]
    assert message["Message-ID"] == "<subscription-expiration-42@example.org>"  # type: ignore[index]


def test_implicit_tls_uses_default_verified_ssl_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts: list[ssl.SSLContext] = []
    constructor_contexts: list[ssl.SSLContext] = []
    real_create_default_context = ssl.create_default_context

    def create_default_context() -> ssl.SSLContext:
        context = real_create_default_context()
        contexts.append(context)
        return context

    class FakeSmtpSsl:
        def __init__(
            self,
            host: str,
            port: int,
            *,
            timeout: int,
            context: ssl.SSLContext,
        ) -> None:
            assert (host, port, timeout) == ("smtp.example.org", 465, 20)
            constructor_contexts.append(context)

        def __enter__(self) -> "FakeSmtpSsl":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            assert (username, password) == ("smtp-user", "smtp-password")

        def send_message(self, message: object) -> None:
            assert message

    monkeypatch.setattr(
        "src.infrastructure.services.email_sender.ssl.create_default_context",
        create_default_context,
    )
    monkeypatch.setattr(
        "src.infrastructure.services.email_sender.smtplib.SMTP_SSL",
        FakeSmtpSsl,
    )
    sender = SmtpEmailSender(
        _smtp_config(port=465, use_ssl=True, use_tls=False)  # type: ignore[arg-type]
    )

    sender._send_sync(
        to="user@example.org",
        subject="subject",
        body="body",
        message_id=None,
    )

    assert len(contexts) == 1
    assert constructor_contexts == contexts
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert contexts[0].check_hostname is True


def test_starttls_uses_same_default_verified_ssl_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts: list[ssl.SSLContext] = []
    starttls_contexts: list[ssl.SSLContext] = []
    real_create_default_context = ssl.create_default_context

    def create_default_context() -> ssl.SSLContext:
        context = real_create_default_context()
        contexts.append(context)
        return context

    class FakeSmtp:
        def __init__(self, host: str, port: int, *, timeout: int) -> None:
            assert (host, port, timeout) == ("smtp.example.org", 587, 20)

        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def ehlo(self) -> None:
            return None

        def starttls(self, *, context: ssl.SSLContext) -> None:
            starttls_contexts.append(context)

        def login(self, username: str, password: str) -> None:
            assert (username, password) == ("smtp-user", "smtp-password")

        def send_message(self, message: object) -> None:
            assert message

    monkeypatch.setattr(
        "src.infrastructure.services.email_sender.ssl.create_default_context",
        create_default_context,
    )
    monkeypatch.setattr(
        "src.infrastructure.services.email_sender.smtplib.SMTP",
        FakeSmtp,
    )
    sender = SmtpEmailSender(
        _smtp_config(port=587, use_ssl=False, use_tls=True)  # type: ignore[arg-type]
    )

    sender._send_sync(
        to="user@example.org",
        subject="subject",
        body="body",
        message_id=None,
    )

    assert len(contexts) == 1
    assert starttls_contexts == contexts
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert contexts[0].check_hostname is True


async def test_persistent_smtp_authentication_failure_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _sender()
    sender._send_sync = Mock(
        side_effect=smtplib.SMTPAuthenticationError(535, b"invalid credentials")
    )
    monkeypatch.setattr(
        "src.infrastructure.services.email_sender.asyncio.to_thread",
        _inline_to_thread,
    )
    monkeypatch.setattr(
        "src.infrastructure.services.email_sender.asyncio.sleep",
        AsyncMock(),
    )

    with pytest.raises(EmailDeliveryError):
        await sender.send(to="user@example.com", subject="subject", body="body")

    assert sender._send_sync.call_count == 2

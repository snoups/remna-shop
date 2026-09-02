from cryptography.fernet import Fernet
from pydantic import SecretStr

from src.application.dto.payment_gateway import YooMoneyGatewaySettingsDto
from src.infrastructure.services.cryptography import CryptographerImpl


def _cryptographer(key: bytes) -> CryptographerImpl:
    cryptographer = object.__new__(CryptographerImpl)
    cryptographer.fernet = Fernet(key)
    return cryptographer


def test_invalid_encrypted_gateway_secret_fails_closed() -> None:
    current = _cryptographer(Fernet.generate_key())
    previous = _cryptographer(Fernet.generate_key())
    stale_ciphertext = previous.encrypt("legacy-secret")

    settings = YooMoneyGatewaySettingsDto(
        wallet_id="wallet",
        secret_key=SecretStr(stale_ciphertext),
    )
    raw = {
        "wallet_id": settings.wallet_id,
        "secret_key": settings.secret_key.get_secret_value(),
    }
    decrypted = current.decrypt_recursive(raw)
    restored = YooMoneyGatewaySettingsDto(**decrypted)

    assert decrypted["secret_key"] is None
    assert restored.is_configured is False


def test_valid_encrypted_gateway_secret_remains_configured() -> None:
    cryptographer = _cryptographer(Fernet.generate_key())
    decrypted = cryptographer.decrypt_recursive(
        {"wallet_id": "wallet", "secret_key": cryptographer.encrypt("secret")}
    )
    restored = YooMoneyGatewaySettingsDto(**decrypted)

    assert restored.secret_key is not None
    assert restored.secret_key.get_secret_value() == "secret"
    assert restored.is_configured is True

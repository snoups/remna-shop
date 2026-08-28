import hashlib
import hmac
import secrets
from typing import Final

from src.application.common.password_hasher import PasswordHasher
from src.core.config import AppConfig
from src.core.constants import (
    PWD_HASH_SCRYPT_DKLEN,
    PWD_HASH_SCRYPT_N,
    PWD_HASH_SCRYPT_P,
    PWD_HASH_SCRYPT_R,
)
from src.core.utils.encoding import b64url_decode, b64url_encode

# A syntactically valid scrypt hash produced with a throwaway password and key.
# Used as a dummy target for verify() when a user/hash is absent, so timing is
# uniform regardless of whether the email exists. Any real crypt_key produces a
# different digest -> always returns False.
_DUMMY_PASSWORD_HASH: Final[str] = (
    "scrypt$16384$8$1$3iwxPRaFhgkuspbRjZ9Srg$t03rWms5Y1agfpb43HVmcZ2bAl4Fhjdv6r8WHNCxoUNbhlOBIXAwovLBu_3NS6SGUGmVDxlumdGB39NT4cZZ7w"
)


class PasswordHasherImpl(PasswordHasher):
    def __init__(self, config: AppConfig) -> None:
        self._key = config.crypt_key.get_secret_value()

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password=f"{password}:{self._key}".encode("utf-8"),
            salt=salt,
            n=PWD_HASH_SCRYPT_N,
            r=PWD_HASH_SCRYPT_R,
            p=PWD_HASH_SCRYPT_P,
            dklen=PWD_HASH_SCRYPT_DKLEN,
        )
        return (
            f"scrypt${PWD_HASH_SCRYPT_N}${PWD_HASH_SCRYPT_R}${PWD_HASH_SCRYPT_P}"
            f"${b64url_encode(salt)}${b64url_encode(digest)}"
        )

    def verify(self, password: str, password_hash: str) -> bool:
        # Always run scrypt against a real hash (the dummy when none given) to keep
        # timing uniform and avoid leaking whether a user/hash exists.
        target = password_hash or _DUMMY_PASSWORD_HASH
        try:
            algorithm, n, r, p, salt_b64, digest_b64 = target.split("$", maxsplit=5)
            if algorithm != "scrypt":
                return False
            expected_digest = b64url_decode(digest_b64)
            check_digest = hashlib.scrypt(
                password=f"{password}:{self._key}".encode("utf-8"),
                salt=b64url_decode(salt_b64),
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(expected_digest),
            )
            ok = hmac.compare_digest(expected_digest, check_digest)
            return ok and bool(password_hash)
        except Exception:
            return False

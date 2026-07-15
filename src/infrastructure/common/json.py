from decimal import Decimal
from typing import Any, Union
from uuid import UUID

import orjson
from aiogram.types import InlineKeyboardMarkup
from pydantic import SecretStr


def encode(data: Any) -> bytes:
    return orjson.dumps(
        data,
        default=_default_processor,
        option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS,
    )


def decode(data: Union[str, bytes]) -> Any:
    return orjson.loads(data)


def bytes_encode(data: Any) -> bytes:
    return encode(data)


def _default_processor(obj: Any) -> Any:
    if isinstance(obj, SecretStr):
        return obj.get_secret_value()
    if isinstance(obj, Decimal):
        return str(obj)
    # orjson serializes exact `uuid.UUID` natively, but not subclasses such as
    # asyncpg's pgproto UUID, which reach here — stringify any UUID subtype.
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, InlineKeyboardMarkup):
        return obj.model_dump()
    raise TypeError(f"Object of type '{type(obj).__name__}' is not JSON serializable")

from decimal import Decimal
from typing import Any, Union

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
    if isinstance(obj, InlineKeyboardMarkup):
        return obj.model_dump()
    raise TypeError(f"Object of type '{type(obj).__name__}' is not JSON serializable")

from typing import Any

_PLATEGA_PAYMENT_METHOD_MAX_ID = 2**31 - 1


def normalize_platega_payment_method(value: Any) -> str | None:
    """Return the canonical provider method or reject unsafe webhook metadata."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0 or value > _PLATEGA_PAYMENT_METHOD_MAX_ID:
            raise ValueError("Invalid Platega paymentMethod id")
        return str(value)
    if not isinstance(value, str):
        raise ValueError("Platega paymentMethod must be an integer id or string")

    payment_method = value.strip()
    if not payment_method:
        return None
    if len(payment_method) > 64 or not payment_method.isprintable():
        raise ValueError("Invalid Platega paymentMethod")
    return payment_method

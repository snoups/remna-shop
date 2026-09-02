import pytest
from pydantic import ValidationError

from src.web.schemas.admin import MergeUsersRequest


def test_merge_resolution_defaults_remain_backward_compatible() -> None:
    request = MergeUsersRequest(source_user_id=11, target_user_id=22, reason="audit")

    assert request.email_resolution == "REJECT"
    assert request.telegram_resolution == "REJECT"
    assert request.payment_resolution == "REJECT"


def test_merge_accepts_only_explicit_supported_resolution_values() -> None:
    request = MergeUsersRequest(
        source_user_id=11,
        target_user_id=22,
        reason="confirmed merge",
        email_resolution="KEEP_TARGET",
        telegram_resolution="KEEP_SOURCE",
        payment_resolution="REKEY_SOURCE",
    )

    assert request.payment_resolution == "REKEY_SOURCE"

    with pytest.raises(ValidationError):
        MergeUsersRequest(
            source_user_id=11,
            target_user_id=22,
            reason="unsafe merge",
            payment_resolution="DROP_SOURCE",  # type: ignore[arg-type]
        )

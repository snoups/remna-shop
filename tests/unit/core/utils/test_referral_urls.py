from src.core.utils.referral_urls import build_web_referral_url


def test_web_referral_url_replaces_cabinet_path_with_canonical_invite_path() -> None:
    result = build_web_referral_url(
        "https://pay.example.com/auth/telegram/webapp?source=bot#fragment",
        "AbC123",
    )

    assert result == "https://pay.example.com/invite/AbC123"


def test_web_referral_url_is_empty_when_web_cabinet_is_disabled() -> None:
    assert build_web_referral_url("", "AbC123") == ""


def test_web_referral_url_rejects_non_absolute_or_unsupported_origins() -> None:
    assert build_web_referral_url("/cabinet", "AbC123") == ""
    assert build_web_referral_url("javascript:alert(1)", "AbC123") == ""

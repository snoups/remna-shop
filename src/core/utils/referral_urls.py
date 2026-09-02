from urllib.parse import quote, urlsplit, urlunsplit


def build_web_referral_url(web_cabinet_url: str, referral_code: str) -> str:
    """Build the canonical Clean Pay registration-and-payment invite URL."""
    raw_url = web_cabinet_url.strip()
    if not raw_url:
        return ""

    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = f"/invite/{quote(referral_code, safe='')}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

from src.infrastructure.services.notification import _escape_html_template_kwargs


def test_escape_html_template_kwargs_escapes_user_controlled_strings() -> None:
    result = _escape_html_template_kwargs(
        {
            "name": "Нигина <3 & \"test\"",
            "items": ["<tag>", 42],
            "nested": {"url": "https://example.com/?a=1&b=<2>"},
            "count": 3,
        }
    )

    assert result == {
        "name": "Нигина &lt;3 &amp; &quot;test&quot;",
        "items": ["&lt;tag&gt;", 42],
        "nested": {"url": "https://example.com/?a=1&amp;b=&lt;2&gt;"},
        "count": 3,
    }

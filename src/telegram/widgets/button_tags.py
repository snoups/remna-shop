import re

from aiogram.enums import ButtonStyle

_TG_EMOJI_RE = re.compile(r'<tg-emoji emoji-id="(\d+)">([^<]*)</tg-emoji>')
_TG_EMOJI_SHORT_RE = re.compile(r'<e id="(\d+)">([^<]*)</e>')
_COLOR_RE = re.compile(r"<c>(primary|success|danger)</c>")


def extract_tg_emoji(text: str) -> tuple[str, str | None]:
    match = _TG_EMOJI_RE.search(text) or _TG_EMOJI_SHORT_RE.search(text)
    if not match:
        return text, None
    emoji_id = match.group(1)
    clean = _TG_EMOJI_SHORT_RE.sub("", _TG_EMOJI_RE.sub("", text))
    return clean, emoji_id


def extract_color(text: str) -> tuple[str, ButtonStyle | None]:
    match = _COLOR_RE.search(text)
    if not match:
        return text, None
    return _COLOR_RE.sub("", text), ButtonStyle(match.group(1))

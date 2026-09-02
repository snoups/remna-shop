import re
from typing import Any, Iterable
from uuid import UUID

from adaptix import Retort
from fluentogram import FluentTranslator, TranslatorHub, TranslatorRunner
from fluentogram.exceptions import KeyNotFoundError
from loguru import logger

from src.core.utils.converters import event_to_key


class TranslatorRunnerImpl(TranslatorRunner):
    def __init__(
        self,
        translators: Iterable[FluentTranslator],
        retort: Retort,
        separator: str = "-",
        collapse_level: int = 2,
    ) -> None:
        super().__init__(translators, separator)
        self.retort = retort
        self.collapse_level = collapse_level

    def get(self, key: str, obj: Any = None, **kwargs: Any) -> str:
        data = self.retort.dump(obj) if obj is not None else {}
        data.update(kwargs)

        sanitized_data = self._sanitize_data(data)
        translated_data = self._translate_values(sanitized_data)
        try:
            text = self._get_translation(key, **translated_data)
        except KeyNotFoundError:
            if kwargs:
                raise
            logger.warning(f"Translation key '{key}' not found, falling back to the key itself")
            text = key
        processed_text = self._postprocess(text)

        return processed_text

    def get_or_raw(self, key_or_text: str, **kwargs: Any) -> str:
        """Translate configured content while preserving intentional literal text.

        Plan names, custom menu labels and already-rendered keyboard captions may be
        either Fluent keys or operator-provided text.  Missing values in this path
        are therefore data, not missing application translations.  Callers that
        require a real Fluent key must continue to use :meth:`get`, which retains
        the warning on a missing key.
        """
        translated_data = self._translate_values(self._sanitize_data(kwargs))
        try:
            text = self._get_translation(key_or_text, **translated_data)
        except KeyNotFoundError:
            text = key_or_text
        return self._postprocess(text)

    def from_event(self, event: Any, **kwargs: Any) -> str:
        raw_name = getattr(event, "event_type", event.__class__.__name__)
        key = event_to_key(raw_name)
        logger.debug(f"Processing event translation for '{key}'")
        return self.get(key, obj=event, **kwargs)

    def _sanitize_data(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: self._sanitize_data(v) for k, v in data.items()}

        if isinstance(data, list):
            return [self._sanitize_data(i) for i in data]

        if data is None:
            return False

        if isinstance(data, UUID):
            return str(data)

        return data

    def _translate_values(self, data: Any) -> Any:
        if (
            isinstance(data, (tuple, list))
            and len(data) == 2
            and isinstance(data[0], str)
            and isinstance(data[1], dict)
        ):
            return self.get(data[0], **self._translate_values(data[1]))

        if isinstance(data, dict) and "key" in data:
            key = data.pop("key")
            return self.get(key, **self._translate_values(data))

        if isinstance(data, list) and all(self._is_translatable_structure(i) for i in data):
            return " ".join(self._translate_values(i) for i in data)

        if isinstance(data, dict):
            return {k: self._translate_values(v) for k, v in data.items()}

        if isinstance(data, list):
            return [self._translate_values(i) for i in data]

        return data

    def _is_translatable_structure(self, item: Any) -> bool:
        is_tuple_style = (
            isinstance(item, (tuple, list)) and len(item) == 2 and isinstance(item[0], str)
        )

        is_dict_style = isinstance(item, dict) and "key" in item
        return is_tuple_style or is_dict_style

    def _postprocess(self, text: str) -> str:
        text = re.sub(
            r"<(\w+)>[\n\r]+(.*?)[\n\r]+</\1>",
            lambda m: f"<{m[1]}>{m[2].rstrip()}</{m[1]}>",
            text,
            flags=re.DOTALL,
        )

        max_newlines = "\n" * self.collapse_level
        pattern = rf"(?:\n[ \t]*){{{self.collapse_level + 1},}}"

        text = re.sub(pattern, max_newlines, text)
        text = re.sub(r"(?<=\n)[ \t]*!empty![ \t]*\n", "", text)

        return re.sub(r"\s*!empty!\s*", "", text)

    def __call__(self, obj: Any = None, **kwargs: Any) -> str:
        key = self._request_line.rstrip(self.separator)
        self._request_line = ""

        return self.get(key, obj=obj, **kwargs)


class TranslatorHubImpl(TranslatorHub):
    def __init__(self, *args: Any, retort: Retort, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retort = retort

    def get_translator_by_locale(self, locale: str) -> TranslatorRunnerImpl:
        translators = self.storage.get_translators_for_language(locale)

        if not translators:
            translators = self.storage.get_translators_for_language(self.root_locale)

        return TranslatorRunnerImpl(
            translators=translators,
            retort=self.retort,
            separator=self.separator,
        )

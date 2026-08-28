from pathlib import Path

from fluent.syntax import FluentParser, FluentSerializer, ast
from fluent_compiler.bundle import FluentBundle
from fluentogram.storage.base import BaseStorage
from fluentogram.translator import FluentTranslator


class LayeredFileStorage(BaseStorage):
    def __init__(
        self,
        user_translations_dir: Path,
        default_translations_dir: Path,
        use_isolating: bool = False,
    ) -> None:
        super().__init__()
        self._user_dir = user_translations_dir
        self._default_dir = default_translations_dir
        self._use_isolating = use_isolating
        self._default_translators: dict[str, FluentTranslator] = {}
        self._load_translations()

    def _make_translator(self, locale: str, texts: list[str]) -> FluentTranslator:
        return FluentTranslator(
            locale=locale,
            translator=FluentBundle.from_string(  # type: ignore[no-untyped-call]
                locale=locale,
                text="\n".join(texts),
                use_isolating=self._use_isolating,
            ),
        )

    def _merge_texts(self, default_texts: list[str], custom_text: str | None) -> list[str]:
        """Merge custom.ftl into the default texts as a single bundle.

        Custom keys must live in the same bundle as the defaults, otherwise Fluent
        message references (``{ key }``) — which only resolve within their own bundle —
        never see the overrides. Default definitions of overridden ids are stripped so
        no duplicate-message junk is produced.
        """
        if not custom_text:
            return default_texts

        custom_ast = FluentParser().parse(custom_text)
        overridden: set[tuple[type, str]] = {
            (type(entry), entry.id.name)
            for entry in custom_ast.body
            if isinstance(entry, (ast.Message, ast.Term))
        }

        default_ast = FluentParser().parse("\n".join(default_texts))
        default_ast.body = [
            entry
            for entry in default_ast.body
            if not (
                isinstance(entry, (ast.Message, ast.Term))
                and (type(entry), entry.id.name) in overridden
            )
        ]
        stripped = FluentSerializer(with_junk=False).serialize(default_ast)
        return [stripped, custom_text]

    def _load_translations(self) -> None:
        # Local dev fallback: assets.default/ not present — behave like FileStorage
        if not self._default_dir.exists():
            for locale_dir in self._user_dir.iterdir():
                if not locale_dir.is_dir():
                    continue
                locale = locale_dir.name
                default_texts = [
                    f.read_text("utf8")
                    for f in sorted(locale_dir.rglob("*.ftl"))
                    if f.name != "custom.ftl"
                ]
                custom_ftl = locale_dir / "custom.ftl"
                custom_text = custom_ftl.read_text("utf8") if custom_ftl.exists() else None
                texts = self._merge_texts(default_texts, custom_text)
                if any(texts):
                    translator = self._make_translator(locale, texts)
                    self._default_translators[locale] = translator
                    self.add_translator(translator)
            return

        for locale_dir in self._default_dir.iterdir():
            if not locale_dir.is_dir():
                continue
            locale = locale_dir.name

            # Load all default .ftl files
            default_texts = [f.read_text("utf8") for f in sorted(locale_dir.rglob("*.ftl"))]

            # Load user's custom.ftl (optional) and merge into the same bundle
            custom_ftl = self._user_dir / locale / "custom.ftl"
            custom_text = custom_ftl.read_text("utf8") if custom_ftl.exists() else None

            texts = self._merge_texts(default_texts, custom_text)
            if any(texts):
                translator = self._make_translator(locale, texts)
                self._default_translators[locale] = translator
                self.add_translator(translator)

    def get_translators_for_language(self, language: str) -> list[FluentTranslator]:
        locale_chain = self._locales_map.get(language, (language,))
        result: list[FluentTranslator] = []
        for locale in locale_chain:
            if locale in self._default_translators:
                result.append(self._default_translators[locale])
        return result

    async def close(self) -> None:
        pass

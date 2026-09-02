from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.application.dto import MenuButtonDto
from src.application.use_cases.misc.queries.menu import GetMenuData
from src.core.enums import Role


async def test_menu_translation_does_not_mutate_cached_settings() -> None:
    button = MenuButtonDto(
        index=1,
        text="menu-privacy",
        is_active=True,
        required_role=Role.USER,
    )
    interactor = object.__new__(GetMenuData)
    interactor.subscription_dao = SimpleNamespace(get_current=AsyncMock(return_value=None))
    interactor.settings_dao = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                referral=SimpleNamespace(enable=True),
                menu=SimpleNamespace(buttons=[button]),
            )
        )
    )
    interactor.bot_service = SimpleNamespace(
        get_referral_url=AsyncMock(return_value="https://t.me/bot?start=ref")
    )
    interactor.i18n = MagicMock()
    interactor.i18n.get_or_raw.return_value = "🛡️ Конфиденциальность"
    interactor.get_available_trial = SimpleNamespace(system=AsyncMock())
    actor = SimpleNamespace(
        id=1,
        is_trial_available=False,
        role=Role.USER,
        referral_code="ref",
    )

    result = await interactor._execute(actor, None)  # type: ignore[arg-type]

    assert button.text == "menu-privacy"
    assert result.custom_buttons[0] is not button
    assert result.custom_buttons[0].text == "🛡️ Конфиденциальность"
    assert button.changed_data == {}

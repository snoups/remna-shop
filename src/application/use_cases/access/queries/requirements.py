from dataclasses import dataclass
from typing import Final, Optional, Union

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from src.application.common import BotService, EventPublisher, Interactor
from src.application.common.dao import SettingsDao
from src.application.common.policy import Permission
from src.application.dto import UserDto
from src.application.events import ChannelCheckErrorEvent

ALLOWED_STATUSES: Final[tuple[ChatMemberStatus, ...]] = (
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
)


@dataclass(frozen=True)
class CheckRulesResultDto:
    is_required: bool
    is_accepted: bool
    rules_url: Optional[str] = None


class CheckRules(Interactor[None, CheckRulesResultDto]):
    required_permission = Permission.PUBLIC

    def __init__(self, settings_dao: SettingsDao) -> None:
        self.settings_dao = settings_dao

    async def _execute(self, actor: UserDto, data: None) -> CheckRulesResultDto:
        settings = await self.settings_dao.get()

        if actor.is_privileged:
            logger.debug(f"{actor.log} skipped rules check due to privileges")
            return CheckRulesResultDto(is_required=False, is_accepted=True)

        if not settings.requirements.rules_required:
            logger.debug(f"Rules check skipped for {actor.log}: requirement is disabled")
            return CheckRulesResultDto(is_required=False, is_accepted=True)

        rules_url = settings.requirements.rules_url

        if actor.is_rules_accepted:
            logger.debug(f"{actor.log} has already accepted rules")
            return CheckRulesResultDto(is_required=True, is_accepted=True, rules_url=rules_url)

        logger.debug(f"{actor.log} must accept rules before proceeding")
        return CheckRulesResultDto(is_required=True, is_accepted=False, rules_url=rules_url)


@dataclass(frozen=True)
class CheckChannelSubscriptionResultDto:
    is_subscribed: bool
    status: Optional[ChatMemberStatus] = None
    channel_url: Optional[str] = None
    error_occurred: bool = False


class CheckChannelSubscription(Interactor[None, CheckChannelSubscriptionResultDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        settings_dao: SettingsDao,
        bot: BotService,
        event_publisher: EventPublisher,
    ) -> None:
        self.settings_dao = settings_dao
        self.bot = bot
        self.event_publisher = event_publisher

    async def _execute(self, actor: UserDto, data: None) -> CheckChannelSubscriptionResultDto:
        settings = await self.settings_dao.get()

        if not settings.requirements.channel_required:
            logger.debug("Channel check skipped: requirement is disabled in settings")
            return CheckChannelSubscriptionResultDto(is_subscribed=True)

        if actor.is_privileged:
            logger.debug(f"{actor.log} skipped channel check due to privileges")
            return CheckChannelSubscriptionResultDto(is_subscribed=True)

        req = settings.requirements
        channel_link = req.channel_link.get_secret_value()
        channel_url = req.channel_url

        if actor.telegram_id is None:
            raise RuntimeError("Channel subscription check requires a Telegram identity")

        chat_id: Union[str, int, None] = None
        if req.channel_has_username:
            chat_id = channel_link
        elif req.channel_id:
            chat_id = req.channel_id

        if chat_id is None:
            logger.warning(
                f"Channel check skipped for '{actor.remna_name}': no valid chat_id or username"
            )
            await self.event_publisher.publish(
                ChannelCheckErrorEvent(
                    telegram_id=actor.telegram_id,
                    username=actor.username,
                    name=actor.name,
                    reason="Channel check skipped: no valid chat_id or username configured",
                )
            )
            return CheckChannelSubscriptionResultDto(is_subscribed=True)
        try:
            member = await self.bot.get_chat_member(chat_id, actor.telegram_id)

            is_subscribed = member.status in ALLOWED_STATUSES
            return CheckChannelSubscriptionResultDto(is_subscribed, member.status, channel_url)

        except TelegramBadRequest as e:
            logger.error(f"Failed to check channel for {actor.log}: '{e}'")
            await self.event_publisher.publish(
                ChannelCheckErrorEvent(
                    telegram_id=actor.telegram_id,
                    username=actor.username,
                    name=actor.name,
                    reason=str(e),
                )
            )

            return CheckChannelSubscriptionResultDto(is_subscribed=True, error_occurred=True)

from dataclasses import dataclass
from typing import Optional

from loguru import logger

from src.application.common import Cryptographer, EventPublisher, Interactor
from src.application.common.dao import AdLinkDao, SettingsDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import AdLinkDto, UserDto
from src.application.events import BlacklistRegistrationAttemptEvent, UserRegisteredEvent
from src.application.use_cases.referral.commands.attachment import AttachReferral, AttachReferralDto
from src.core.config import AppConfig
from src.core.enums import Locale, Role
from src.core.utils.converters import user_name_clean


@dataclass
class GetOrCreateUserDto:
    telegram_id: int
    username: Optional[str]
    full_name: str
    language_code: Optional[str]
    is_chat_member_event: bool = False
    referral_code: Optional[str] = None
    ad_link_code: Optional[str] = None
    role: Role = Role.USER


class GetOrCreateUser(Interactor[GetOrCreateUserDto, Optional[UserDto]]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        settings_dao: SettingsDao,
        config: AppConfig,
        cryptographer: Cryptographer,
        event_publisher: EventPublisher,
        attach_referral: AttachReferral,
        ad_link_dao: AdLinkDao,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.settings_dao = settings_dao
        self.config = config
        self.cryptographer = cryptographer
        self.event_publisher = event_publisher
        self.attach_referral = attach_referral
        self.ad_link_dao = ad_link_dao

    async def _execute(self, actor: UserDto, data: GetOrCreateUserDto) -> Optional[UserDto]:
        is_owner = data.telegram_id == self.config.bot.owner_id

        async with self.uow:
            user = await self.user_dao.get_by_telegram_id(data.telegram_id)
            if user:
                if is_owner and user.role != Role.OWNER:
                    user = await self._transfer_owner_role(user)
                    await self.uow.commit()
                    logger.info(
                        f"Owner role transferred to '{user.remna_name}' due to BOT_OWNER_ID change"
                    )
                return user

            if data.is_chat_member_event:
                logger.debug(
                    f"Skipping user creation for '{data.telegram_id}' due to chat member event"
                )
                return None

            role = Role.OWNER if is_owner else None

            settings = await self.settings_dao.get()
            is_blocked = data.telegram_id in settings.blacklist.blocked_ids

            ad_link = await self._resolve_ad_link(data.ad_link_code)
            ad_link_id = ad_link.id if ad_link else None

            async def persist(referral_code: str) -> UserDto:
                return await self.user_dao.create(
                    self._create_user_dto(
                        data,
                        referral_code=referral_code,
                        is_blocked=is_blocked,
                        ad_link_id=ad_link_id,
                        role=role,
                    )
                )

            user = await self.uow.persist_with_unique_code(
                generate=lambda: self.cryptographer.generate_unique_code(
                    self.user_dao.get_by_referral_code
                ),
                persist=persist,
                column="referral_code",
            )

            if is_owner:
                old_owners = await self.user_dao.filter_by_role([Role.OWNER])
                for old_owner in old_owners:
                    if old_owner.id != user.id:
                        old_owner.role = Role.DEV
                        await self.user_dao.update(old_owner)
                        logger.info(
                            f"Owner role revoked from '{old_owner.remna_name}' "
                            f"due to BOT_OWNER_ID change"
                        )

            await self.uow.commit()

        if is_blocked:
            logger.warning(f"New user {user.log} created as blocked (found in blacklist)")
            await self.event_publisher.publish(
                BlacklistRegistrationAttemptEvent(
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                    username=user.username,
                    name=user.name,
                    email=user.email,
                )
            )
            return user

        referrer = None
        if data.referral_code:
            referrer = await self.attach_referral.system(
                AttachReferralDto(user.id, data.referral_code)
            )

        await self.event_publisher.publish(
            UserRegisteredEvent(
                user_id=user.id,
                telegram_id=user.telegram_id,
                username=user.username,
                name=user.name,
                email=user.email,
                referrer_user_id=referrer.id if referrer else None,
                referrer_telegram_id=referrer.telegram_id if referrer else None,
                referrer_email=referrer.email if referrer else None,
                referrer_username=referrer.username if referrer else None,
                referrer_name=referrer.name if referrer else None,
                ad_link_id=ad_link.id if ad_link else None,
                ad_link_name=ad_link.name if ad_link else None,
                ad_link_code=ad_link.code if ad_link else None,
            )
        )

        logger.info(f"New user {user.log} created")
        return user

    async def _resolve_ad_link(self, ad_link_code: Optional[str]) -> Optional[AdLinkDto]:
        if not ad_link_code:
            return None
        ad_link = await self.ad_link_dao.get_by_code(ad_link_code)
        if ad_link and ad_link.is_active:
            return ad_link
        return None

    async def _transfer_owner_role(self, new_owner: UserDto) -> UserDto:
        old_owners = await self.user_dao.filter_by_role([Role.OWNER])
        for old_owner in old_owners:
            old_owner.role = Role.DEV
            await self.user_dao.update(old_owner)
        new_owner.role = Role.OWNER
        return await self.user_dao.update(new_owner) or new_owner

    def _create_user_dto(
        self,
        data: GetOrCreateUserDto,
        *,
        referral_code: str,
        is_blocked: bool = False,
        ad_link_id: Optional[int] = None,
        role: Optional[Role] = None,
    ) -> UserDto:
        if data.language_code in self.config.locales:
            locale = Locale(data.language_code)
        else:
            locale = self.config.default_locale

        return UserDto(
            telegram_id=data.telegram_id,
            username=data.username,
            referral_code=referral_code,
            name=user_name_clean(data.full_name, data.telegram_id),
            role=role if role is not None else data.role,
            language=locale,
            is_blocked=is_blocked,
            ad_link_id=ad_link_id,
        )


@dataclass(frozen=True)
class UpdateUserProfileDto:
    user: UserDto
    username: Optional[str]
    full_name: str
    language_code: Optional[str]
    telegram_id: int


class UpdateUserProfile(Interactor[UpdateUserProfileDto, UserDto]):
    required_permission = None

    def __init__(self, uow: UnitOfWork, user_dao: UserDao, config: AppConfig) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.config = config

    async def _execute(self, actor: UserDto, data: UpdateUserProfileDto) -> UserDto:
        user = data.user
        changed = False

        new_username = data.username
        if user.username != new_username:
            logger.debug(
                f"User '{user.remna_name}' username changed from "
                f"'{user.username}' to '{new_username}'"
            )
            user.username = new_username
            changed = True

        new_name = user_name_clean(data.full_name, data.telegram_id)
        if user.name != new_name:
            logger.debug(
                f"User '{user.remna_name}' name changed from '{user.name}' to '{new_name}'"
            )
            user.name = new_name
            changed = True

        new_language = data.language_code
        if new_language and user.language != new_language:
            if new_language in self.config.locales:
                logger.debug(
                    f"User '{user.remna_name}' language changed from "
                    f"'{user.language}' to '{new_language}'"
                )
                user.language = Locale(new_language)
                changed = True
            else:
                logger.warning(
                    f"User '{user.remna_name}' language '{new_language}' is not supported, "
                    f"keeping current '{user.language}'"
                )

        if not changed:
            return user

        async with self.uow:
            updated_user = await self.user_dao.update(user)
            if updated_user:
                logger.info(f"{user.log} profile updated from Telegram data")
            await self.uow.commit()

        return updated_user or user

from typing import Optional

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import SettingsDao
from src.application.dto import SettingsDto
from src.core.constants import TTL_6H
from src.infrastructure.database.models import Settings
from src.infrastructure.redis.cache import invalidate_cache, provide_cache
from src.infrastructure.redis.keys import SETTINGS_PREFIX

from .base import BaseDaoImpl


class SettingsDaoImpl(SettingsDao, BaseDaoImpl):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
        redis: Redis,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort
        self.redis = redis

        self._convert_to_dto = self.conversion_retort.get_converter(Settings, SettingsDto)

    @invalidate_cache(key_builder=SETTINGS_PREFIX)
    async def create_default(self) -> SettingsDto:
        settings_data = self.retort.dump(SettingsDto())
        settings_data.pop("id", None)
        db_settings = Settings(**settings_data)
        self.session.add(db_settings)

        await self.session.flush()

        logger.debug("Created default settings")
        return self._convert_to_dto(db_settings)

    async def exists(self) -> bool:
        stmt = select(Settings.id).limit(1)
        return await self.session.scalar(stmt) is not None

    @provide_cache(prefix=SETTINGS_PREFIX, ttl=TTL_6H)
    async def get(self) -> SettingsDto:
        stmt = select(Settings).limit(1)
        db_settings = await self.session.scalar(stmt)

        if not db_settings:
            # Invariant: CreateDefaultSettings seeds the row at startup before any
            # request reaches this DAO. A missing row here means the bootstrap did
            # not run — fail loudly instead of caching an uncommitted phantom whose
            # id would never match on a later update().
            raise RuntimeError("Settings row is missing; default settings were not initialized")

        logger.debug("Global settings retrieved")
        return self._convert_to_dto(db_settings)

    async def get_for_update(self) -> SettingsDto:
        """Load the authoritative settings row and hold its transaction row lock.

        This path intentionally bypasses Redis. ``populate_existing`` also refreshes
        an instance already present in the SQLAlchemy identity map, so callers never
        take a lock while continuing with a stale settings snapshot.
        """
        stmt = select(Settings).limit(1).with_for_update().execution_options(populate_existing=True)
        db_settings = await self.session.scalar(stmt)

        if not db_settings:
            raise RuntimeError("Settings row is missing; default settings were not initialized")

        logger.debug("Authoritative global settings retrieved for update")
        return self._convert_to_dto(db_settings)

    @invalidate_cache(key_builder=SETTINGS_PREFIX)
    async def update(self, settings: SettingsDto) -> Optional[SettingsDto]:
        if not settings.changed_data:
            logger.warning("No changes detected in settings, skipping update")
            return None

        values_to_update = self._serialize_for_update(settings, SettingsDto, Settings)

        stmt = (
            update(Settings)
            .where(Settings.id == settings.id)
            .values(**values_to_update)
            .returning(Settings)
        )
        db_settings = await self.session.scalar(stmt)

        if not db_settings:
            logger.warning(f"Failed to update settings with ID '{settings.id}': record not found")
            return None

        logger.debug(f"Settings updated with keys '{list(values_to_update.keys())}'")
        return self._convert_to_dto(db_settings)

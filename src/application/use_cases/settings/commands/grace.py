from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from loguru import logger
from remnapy.enums import TrafficLimitStrategy

from src.application.common import Interactor
from src.application.common.dao import SettingsDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import SettingsDto, UserDto

TRAFFIC_MIN = 0
TRAFFIC_MAX = 1_048_576  # 1 TB in MB
DURATION_MIN = 0
DURATION_MAX = 365


class ToggleGraceEnabled(Interactor[None, Optional[SettingsDto]]):
    required_permission = Permission.SETTINGS_EXTRA

    def __init__(self, uow: UnitOfWork, settings_dao: SettingsDao) -> None:
        self.uow = uow
        self.settings_dao = settings_dao

    async def _execute(self, actor: UserDto, data: None) -> Optional[SettingsDto]:
        async with self.uow:
            settings = await self.settings_dao.get()
            settings.grace.enabled = not settings.grace.enabled
            updated = await self.settings_dao.update(settings)
            await self.uow.commit()
        logger.info(f"{actor.log} Toggled grace.enabled: {settings.grace.enabled}")
        return updated


@dataclass(frozen=True)
class UpdateGraceTrafficDto:
    raw_value: str


class UpdateGraceTraffic(Interactor[UpdateGraceTrafficDto, Optional[SettingsDto]]):
    required_permission = Permission.SETTINGS_EXTRA

    def __init__(self, uow: UnitOfWork, settings_dao: SettingsDao) -> None:
        self.uow = uow
        self.settings_dao = settings_dao

    async def _execute(self, actor: UserDto, data: UpdateGraceTrafficDto) -> Optional[SettingsDto]:
        mb = int(data.raw_value.strip())
        if mb < TRAFFIC_MIN or mb > TRAFFIC_MAX:
            raise ValueError(f"Traffic must be between {TRAFFIC_MIN} and {TRAFFIC_MAX} MB")
        async with self.uow:
            settings = await self.settings_dao.get()
            settings.grace.traffic_mb = mb
            updated = await self.settings_dao.update(settings)
            await self.uow.commit()
        logger.info(f"{actor.log} Set grace.traffic_mb: {mb}")
        return updated


@dataclass(frozen=True)
class SetGraceStrategyDto:
    strategy: TrafficLimitStrategy


class SetGraceStrategy(Interactor[SetGraceStrategyDto, Optional[SettingsDto]]):
    required_permission = Permission.SETTINGS_EXTRA

    def __init__(self, uow: UnitOfWork, settings_dao: SettingsDao) -> None:
        self.uow = uow
        self.settings_dao = settings_dao

    async def _execute(self, actor: UserDto, data: SetGraceStrategyDto) -> Optional[SettingsDto]:
        async with self.uow:
            settings = await self.settings_dao.get()
            settings.grace.traffic_strategy = data.strategy
            updated = await self.settings_dao.update(settings)
            await self.uow.commit()
        logger.info(f"{actor.log} Set grace.traffic_strategy: {data.strategy}")
        return updated


@dataclass(frozen=True)
class UpdateGraceDurationDto:
    raw_value: str


class UpdateGraceDuration(Interactor[UpdateGraceDurationDto, Optional[SettingsDto]]):
    required_permission = Permission.SETTINGS_EXTRA

    def __init__(self, uow: UnitOfWork, settings_dao: SettingsDao) -> None:
        self.uow = uow
        self.settings_dao = settings_dao

    async def _execute(self, actor: UserDto, data: UpdateGraceDurationDto) -> Optional[SettingsDto]:
        days = int(data.raw_value.strip())
        if days < DURATION_MIN or days > DURATION_MAX:
            raise ValueError(f"Duration must be between {DURATION_MIN} and {DURATION_MAX} days")
        async with self.uow:
            settings = await self.settings_dao.get()
            settings.grace.duration_days = days
            updated = await self.settings_dao.update(settings)
            await self.uow.commit()
        logger.info(f"{actor.log} Set grace.duration_days: {days}")
        return updated


@dataclass(frozen=True)
class UpdateGraceTagDto:
    raw_value: str


class UpdateGraceTag(Interactor[UpdateGraceTagDto, Optional[SettingsDto]]):
    required_permission = Permission.SETTINGS_EXTRA

    def __init__(self, uow: UnitOfWork, settings_dao: SettingsDao) -> None:
        self.uow = uow
        self.settings_dao = settings_dao

    async def _execute(self, actor: UserDto, data: UpdateGraceTagDto) -> Optional[SettingsDto]:
        tag = data.raw_value.strip() or None
        async with self.uow:
            settings = await self.settings_dao.get()
            settings.grace.tag = tag
            updated = await self.settings_dao.update(settings)
            await self.uow.commit()
        logger.info(f"{actor.log} Set grace.tag: {tag}")
        return updated


@dataclass(frozen=True)
class ToggleGraceInternalSquadDto:
    squad_uuid: UUID


class ToggleGraceInternalSquad(Interactor[ToggleGraceInternalSquadDto, Optional[SettingsDto]]):
    required_permission = Permission.SETTINGS_EXTRA

    def __init__(self, uow: UnitOfWork, settings_dao: SettingsDao) -> None:
        self.uow = uow
        self.settings_dao = settings_dao

    async def _execute(
        self, actor: UserDto, data: ToggleGraceInternalSquadDto
    ) -> Optional[SettingsDto]:
        async with self.uow:
            settings = await self.settings_dao.get()
            squads = settings.grace.internal_squads.copy()
            if data.squad_uuid in squads:
                squads.remove(data.squad_uuid)
            else:
                squads.append(data.squad_uuid)
            settings.grace.internal_squads = squads
            updated = await self.settings_dao.update(settings)
            await self.uow.commit()
        logger.info(f"{actor.log} Toggled grace.internal_squads: {data.squad_uuid}")
        return updated


@dataclass(frozen=True)
class SetGraceExternalSquadDto:
    squad_uuid: Optional[UUID]


class SetGraceExternalSquad(Interactor[SetGraceExternalSquadDto, Optional[SettingsDto]]):
    required_permission = Permission.SETTINGS_EXTRA

    def __init__(self, uow: UnitOfWork, settings_dao: SettingsDao) -> None:
        self.uow = uow
        self.settings_dao = settings_dao

    async def _execute(
        self, actor: UserDto, data: SetGraceExternalSquadDto
    ) -> Optional[SettingsDto]:
        async with self.uow:
            settings = await self.settings_dao.get()
            settings.grace.external_squad = data.squad_uuid
            updated = await self.settings_dao.update(settings)
            await self.uow.commit()
        logger.info(f"{actor.log} Set grace.external_squad: {data.squad_uuid}")
        return updated

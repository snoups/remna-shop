from dataclasses import dataclass
from typing import get_type_hints

from adaptix import Retort
from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import PaymentGatewayDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.core.exceptions import GatewayNotConfiguredError


class MovePaymentGatewayUp(Interactor[int, None]):
    required_permission = Permission.REMNASHOP_GATEWAYS

    def __init__(self, uow: UnitOfWork, gateway_dao: PaymentGatewayDao) -> None:
        self.uow = uow
        self.gateway_dao = gateway_dao

    async def _execute(self, actor: UserDto, gateway_id: int) -> None:
        async with self.uow:
            gateways = await self.gateway_dao.get_all()
            gateways.sort(key=lambda g: g.order_index)

            index = next((i for i, g in enumerate(gateways) if g.id == gateway_id), None)

            if index is None:
                logger.warning(
                    f"Payment gateway with id '{gateway_id}' not found for move operation"
                )
                return

            if index == 0:
                gateway = gateways.pop(0)
                gateways.append(gateway)
                logger.debug(f"Payment gateway '{gateway_id}' moved from top to bottom")
            else:
                gateways[index - 1], gateways[index] = gateways[index], gateways[index - 1]
                logger.debug(f"Payment gateway '{gateway_id}' moved up one position")

            for i, g in enumerate(gateways, start=1):
                if g.order_index != i:
                    g.order_index = i
                    await self.gateway_dao.update(g)

            await self.uow.commit()

        logger.info(f"{actor.log} Moved payment gateway '{gateway_id}' up successfully")


class TogglePaymentGatewayActive(Interactor[int, None]):
    required_permission = Permission.REMNASHOP_GATEWAYS

    def __init__(
        self,
        uow: UnitOfWork,
        gateway_dao: PaymentGatewayDao,
    ) -> None:
        self.uow = uow
        self.gateway_dao = gateway_dao

    async def _execute(self, actor: UserDto, gateway_id: int) -> None:
        async with self.uow:
            gateway = await self.gateway_dao.get_by_id(gateway_id)

            if not gateway:
                raise ValueError(f"Payment gateway with id '{gateway_id}' not found")

            if gateway.settings and not gateway.settings.is_configured:
                raise GatewayNotConfiguredError(f"Gateway '{gateway_id}' is not configured")

            old_status = gateway.is_active
            gateway.is_active = not old_status

            await self.gateway_dao.update(gateway)
            await self.uow.commit()

        logger.info(
            f"{actor.log} Updated payment gateway '{gateway_id}' "
            f"active status from '{old_status}' to '{gateway.is_active}'"
        )


@dataclass(frozen=True)
class UpdatePaymentGatewaySettingsDto:
    gateway_id: int
    field_name: str
    value: str


class UpdatePaymentGatewaySettings(Interactor[UpdatePaymentGatewaySettingsDto, None]):
    required_permission = Permission.REMNASHOP_GATEWAYS

    def __init__(self, uow: UnitOfWork, gateway_dao: PaymentGatewayDao, retort: Retort) -> None:
        self.uow = uow
        self.gateway_dao = gateway_dao
        self.retort = retort

    async def _execute(self, actor: UserDto, data: UpdatePaymentGatewaySettingsDto) -> None:
        async with self.uow:
            gateway = await self.gateway_dao.get_by_id(data.gateway_id)

            if not gateway or not gateway.settings:
                raise GatewayNotConfiguredError(f"Gateway '{data.gateway_id}' is not configured")

            try:
                settings_type = type(gateway.settings)
                field_type = get_type_hints(settings_type).get(data.field_name)

                if not field_type:
                    raise ValueError(
                        f"Field '{data.field_name}' not found in {settings_type.__name__}"
                    )

                new_value = self.retort.load(data.value, field_type)
                setattr(gateway.settings, data.field_name, new_value)

                await self.gateway_dao.update(gateway)
                await self.uow.commit()

                logger.info(
                    f"{actor.log} Updated '{data.field_name}' for gateway '{data.gateway_id}'"
                )

            except ValueError as e:
                logger.warning(f"{actor.log} Invalid value for field '{data.field_name}': {e}")
                raise


@dataclass(frozen=True)
class ResetPaymentGatewaySettingsDto:
    gateway_id: int
    field_name: str


class ResetPaymentGatewaySettingsField(Interactor[ResetPaymentGatewaySettingsDto, bool]):
    required_permission = Permission.REMNASHOP_GATEWAYS

    def __init__(self, uow: UnitOfWork, gateway_dao: PaymentGatewayDao) -> None:
        self.uow = uow
        self.gateway_dao = gateway_dao

    async def _execute(self, actor: UserDto, data: ResetPaymentGatewaySettingsDto) -> bool:
        async with self.uow:
            gateway = await self.gateway_dao.get_by_id(data.gateway_id)

            if not gateway or not gateway.settings:
                raise GatewayNotConfiguredError(f"Gateway '{data.gateway_id}' is not configured")

            settings_type = type(gateway.settings)
            if data.field_name not in get_type_hints(settings_type):
                raise ValueError(f"Field '{data.field_name}' not found in {settings_type.__name__}")

            setattr(gateway.settings, data.field_name, None)

            deactivated = False
            if gateway.is_active and not gateway.settings.is_configured:
                gateway.is_active = False
                deactivated = True

            await self.gateway_dao.update(gateway)
            await self.uow.commit()

        logger.info(
            f"{actor.log} Reset '{data.field_name}' for gateway '{data.gateway_id}' "
            f"(deactivated={deactivated})"
        )
        return deactivated

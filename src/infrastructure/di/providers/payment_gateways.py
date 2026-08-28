from __future__ import annotations

from typing import Type

from aiogram import Bot
from dishka import Provider, Scope, provide
from loguru import logger

from src.application.dto.payment_gateway import PaymentGatewayDto
from src.core.config import AppConfig
from src.core.enums import PaymentGatewayType
from src.infrastructure.payment_gateways import (
    BasePaymentGateway,
    CryptomusGateway,
    CryptoPayGateway,
    FreeKassaGateway,
    HeleketGateway,
    MulenPayGateway,
    PayMasterGateway,
    PaymentGatewayFactory,
    PlategaGateway,
    RobokassaGateway,
    RollyPayGateway,
    TelegramStarsGateway,
    UrlPayGateway,
    ValutixGateway,
    WataGateway,
    YookassaGateway,
    YoomoneyGateway,
)

GATEWAY_MAP: dict[PaymentGatewayType, Type[BasePaymentGateway]] = {
    PaymentGatewayType.TELEGRAM_STARS: TelegramStarsGateway,
    PaymentGatewayType.YOOKASSA: YookassaGateway,
    PaymentGatewayType.YOOMONEY: YoomoneyGateway,
    PaymentGatewayType.CRYPTOMUS: CryptomusGateway,
    PaymentGatewayType.HELEKET: HeleketGateway,
    PaymentGatewayType.CRYPTOPAY: CryptoPayGateway,
    PaymentGatewayType.FREEKASSA: FreeKassaGateway,
    PaymentGatewayType.MULENPAY: MulenPayGateway,
    PaymentGatewayType.PAYMASTER: PayMasterGateway,
    PaymentGatewayType.PLATEGA: PlategaGateway,
    PaymentGatewayType.ROBOKASSA: RobokassaGateway,
    PaymentGatewayType.ROLLYPAY: RollyPayGateway,
    PaymentGatewayType.URLPAY: UrlPayGateway,
    PaymentGatewayType.VALUTIX: ValutixGateway,
    PaymentGatewayType.WATA: WataGateway,
}


class PaymentGatewaysProvider(Provider):
    scope = Scope.APP

    def __init__(self) -> None:
        super().__init__()
        self._cached_gateways: dict[PaymentGatewayType, BasePaymentGateway] = {}

    @provide()
    def get_gateway_factory(self, bot: Bot, config: AppConfig) -> PaymentGatewayFactory:
        def get_instance(gateway: PaymentGatewayDto) -> BasePaymentGateway:
            gateway_type = gateway.type

            if gateway_type in self._cached_gateways:
                cached_gateway = self._cached_gateways[gateway_type]

                if cached_gateway.data != gateway:
                    logger.warning(
                        f"Gateway '{gateway_type}' data changed. Re-initializing instance"
                    )
                    del self._cached_gateways[gateway_type]

            if gateway_type not in self._cached_gateways:
                gateway_instance = GATEWAY_MAP.get(gateway_type)

                if not gateway_instance:
                    raise ValueError(f"Unknown gateway type '{gateway_type}'")

                self._cached_gateways[gateway_type] = gateway_instance(
                    gateway=gateway, bot=bot, config=config
                )
                logger.debug(f"Initialized new gateway '{gateway_type}' instance")

            return self._cached_gateways[gateway_type]

        return get_instance

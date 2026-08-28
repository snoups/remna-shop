from datetime import datetime
from typing import Any

from adaptix import (
    ExtraSkip,
    P,
    Retort,
    as_is_dumper,
    dumper,
    loader,
    name_mapping,
)
from adaptix._internal.provider.loc_stack_filtering import OriginSubclassLSC
from adaptix.conversion import ConversionRetort, coercer, link_function
from aiogram.enums import ButtonStyle
from dishka import Provider, Scope, provide
from pydantic import SecretStr, TypeAdapter

from src.application.common import Cryptographer
from src.application.dto import (
    AccessSettingsDto,
    BackupSettingsDto,
    BlacklistSettingsDto,
    ExtraSettingsDto,
    GraceSettingsDto,
    MenuButtonDto,
    MenuSettingsDto,
    MessagePayloadDto,
    NotificationsSettingsDto,
    PlanSnapshotDto,
    PriceDetailsDto,
    ReferralSettingsDto,
    RequirementSettingsDto,
    ResetFeatureSettingsDto,
)
from src.application.dto.payment_gateway import (
    CryptomusGatewaySettingsDto,
    CryptoPayGatewaySettingsDto,
    FreeKassaGatewaySettingsDto,
    HeleketGatewaySettingsDto,
    MulenPayGatewaySettingsDto,
    PayMasterGatewaySettingsDto,
    PlategaGatewaySettingsDto,
    RoboKassaGatewaySettingsDto,
    RollyPaySettingsDto,
    TelegramStarsGatewaySettingsDto,
    UrlPayGatewaySettingsDto,
    ValutixGatewaySettingsDto,
    WataGatewaySettingsDto,
    YooKassaGatewaySettingsDto,
    YooMoneyGatewaySettingsDto,
)
from src.core.enums import MediaType, PaymentGatewayType, ReferralLevel, Role
from src.core.types import AnyKeyboard
from src.infrastructure.database.models import PaymentGateway
from src.infrastructure.redis.key_builder import StorageKey, serialize_storage_key


class RetortProvider(Provider):
    scope = Scope.APP

    @provide
    def get_retort(self) -> Retort:
        retort = Retort(
            recipe=[
                loader(
                    P[MessagePayloadDto].reply_markup,
                    lambda x: TypeAdapter(AnyKeyboard).validate_python(x) if x else None,
                ),
                dumper(P[MessagePayloadDto].reply_markup, lambda x: x.model_dump() if x else None),
                dumper(P[MessagePayloadDto].media_type, lambda x: MediaType(x) if x else None),
                #
                loader(
                    datetime,
                    lambda x: x if isinstance(x, datetime) else datetime.fromisoformat(x),
                ),
                as_is_dumper(datetime),
                name_mapping(extra_in=ExtraSkip()),
                #
                loader(
                    dict[ReferralLevel, int],
                    lambda data: {ReferralLevel(int(k)): v for k, v in data.items()},
                ),
                dumper(OriginSubclassLSC(StorageKey), serialize_storage_key),
                #
                loader(
                    P[MenuButtonDto].color,
                    lambda x: ButtonStyle(x) if x else None,
                ),
                loader(SecretStr, SecretStr),
                dumper(
                    SecretStr, lambda v: v.get_secret_value() if isinstance(v, SecretStr) else v
                ),
            ],
            strict_coercion=False,
        )

        return retort

    @provide
    def get_conversion_retort(
        self,
        retort: Retort,
        cryptographer: Cryptographer,
    ) -> ConversionRetort:
        def get_settings_dto(pg_type: PaymentGatewayType, settings_dict: dict) -> Any:
            type_mapping = {
                PaymentGatewayType.TELEGRAM_STARS: TelegramStarsGatewaySettingsDto,
                PaymentGatewayType.YOOKASSA: YooKassaGatewaySettingsDto,
                PaymentGatewayType.YOOMONEY: YooMoneyGatewaySettingsDto,
                PaymentGatewayType.CRYPTOMUS: CryptomusGatewaySettingsDto,
                PaymentGatewayType.HELEKET: HeleketGatewaySettingsDto,
                PaymentGatewayType.CRYPTOPAY: CryptoPayGatewaySettingsDto,
                PaymentGatewayType.FREEKASSA: FreeKassaGatewaySettingsDto,
                PaymentGatewayType.MULENPAY: MulenPayGatewaySettingsDto,
                PaymentGatewayType.PAYMASTER: PayMasterGatewaySettingsDto,
                PaymentGatewayType.PLATEGA: PlategaGatewaySettingsDto,
                PaymentGatewayType.ROBOKASSA: RoboKassaGatewaySettingsDto,
                PaymentGatewayType.ROLLYPAY: RollyPaySettingsDto,
                PaymentGatewayType.URLPAY: UrlPayGatewaySettingsDto,
                PaymentGatewayType.VALUTIX: ValutixGatewaySettingsDto,
                PaymentGatewayType.WATA: WataGatewaySettingsDto,
            }

            dto_class = type_mapping.get(pg_type)
            if dto_class is None:
                raise ValueError(f"Unknown gateway type: {pg_type}")

            settings_dict = cryptographer.decrypt_recursive(settings_dict)
            return dto_class(**settings_dict)

        def convert_settings(payment_gateway: PaymentGateway) -> Any:
            if not payment_gateway.settings:
                return None
            return get_settings_dto(payment_gateway.type, payment_gateway.settings)

        conversion_retort = ConversionRetort(
            recipe=[
                dumper(SecretStr, lambda v: v.get_secret_value()),
                coercer(Role, Role, lambda v: Role(v)),
                #
                coercer(dict, MessagePayloadDto, retort.get_loader(MessagePayloadDto)),
                #
                coercer(dict, PlanSnapshotDto, retort.get_loader(PlanSnapshotDto)),
                coercer(dict, AccessSettingsDto, retort.get_loader(AccessSettingsDto)),
                coercer(dict, RequirementSettingsDto, retort.get_loader(RequirementSettingsDto)),
                coercer(
                    dict, NotificationsSettingsDto, retort.get_loader(NotificationsSettingsDto)
                ),
                coercer(dict, ReferralSettingsDto, retort.get_loader(ReferralSettingsDto)),
                coercer(dict, BackupSettingsDto, retort.get_loader(BackupSettingsDto)),
                coercer(dict, BlacklistSettingsDto, retort.get_loader(BlacklistSettingsDto)),
                coercer(dict, MenuSettingsDto, retort.get_loader(MenuSettingsDto)),
                coercer(dict, ExtraSettingsDto, retort.get_loader(ExtraSettingsDto)),
                coercer(dict, GraceSettingsDto, retort.get_loader(GraceSettingsDto)),
                coercer(dict, ResetFeatureSettingsDto, retort.get_loader(ResetFeatureSettingsDto)),
                coercer(dict, MenuButtonDto, retort.get_loader(MenuButtonDto)),
                #
                coercer(dict, PriceDetailsDto, retort.get_loader(PriceDetailsDto)),
                #
                link_function(convert_settings, "settings"),
                *[
                    coercer(dict, dto_class, retort.get_loader(dto_class))
                    for dto_class in [
                        TelegramStarsGatewaySettingsDto,
                        YooKassaGatewaySettingsDto,
                        YooMoneyGatewaySettingsDto,
                        CryptomusGatewaySettingsDto,
                        HeleketGatewaySettingsDto,
                        CryptoPayGatewaySettingsDto,
                        FreeKassaGatewaySettingsDto,
                        MulenPayGatewaySettingsDto,
                        PayMasterGatewaySettingsDto,
                        PlategaGatewaySettingsDto,
                        RoboKassaGatewaySettingsDto,
                        RollyPaySettingsDto,
                        UrlPayGatewaySettingsDto,
                        ValutixGatewaySettingsDto,
                        WataGatewaySettingsDto,
                    ]
                ],
            ]
        )
        return conversion_retort

import uuid
from dataclasses import dataclass
from uuid import UUID

from loguru import logger

from src.application.common import (
    EventPublisher,
    Interactor,
    Notifier,
    Redirect,
    TranslatorHub,
)
from src.application.common.dao import (
    PaymentGatewayDao,
    ReferralDao,
    SubscriptionDao,
    TransactionDao,
    UserDao,
)
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import (
    MessagePayloadDto,
    PaymentResultDto,
    PlanSnapshotDto,
    PriceDetailsDto,
    TransactionDto,
    UserDto,
)
from src.application.dto.payment_gateway import (
    CryptomusGatewaySettingsDto,
    CryptoPayGatewaySettingsDto,
    FreeKassaGatewaySettingsDto,
    HeleketGatewaySettingsDto,
    MulenPayGatewaySettingsDto,
    PayMasterGatewaySettingsDto,
    PaymentGatewayDto,
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
from src.application.events import UserPurchaseEvent
from src.application.use_cases.gateways.queries.providers import GetPaymentGatewayInstance
from src.application.use_cases.referral.commands.rewards import (
    AssignReferralRewards,
    AssignReferralRewardsDto,
)
from src.application.use_cases.subscription.commands.purchase import (
    PurchaseSubscription,
    PurchaseSubscriptionDto,
)
from src.core.enums import (
    Currency,
    PaymentGatewayType,
    PurchaseType,
    Role,
    SystemNotificationType,
    TransactionStatus,
)
from src.core.exceptions import PurchaseError, TransactionNotRetryableError
from src.core.utils.i18n_helpers import (
    i18n_format_days,
    i18n_format_device_limit,
    i18n_format_traffic_limit,
)


class CreateDefaultPaymentGateway(Interactor[None, None]):
    required_permission = None

    def __init__(self, uow: UnitOfWork, gateway_dao: PaymentGatewayDao) -> None:
        self.uow = uow
        self.gateway_dao = gateway_dao

    async def _execute(self, actor: UserDto, data: None) -> None:
        async with self.uow:
            created_any = False

            for gateway_type in PaymentGatewayType:
                if await self.gateway_dao.get_by_type(gateway_type):
                    continue

                created_any = True

                is_active = gateway_type == PaymentGatewayType.TELEGRAM_STARS

                settings_map = {
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
                dto_class = settings_map.get(gateway_type)
                settings = dto_class() if dto_class else None

                await self.gateway_dao.create(
                    PaymentGatewayDto(
                        type=gateway_type,
                        currency=Currency.from_gateway_type(gateway_type),
                        is_active=is_active,
                        settings=settings,
                    )
                )
                logger.info(f"Payment gateway '{gateway_type}' created")

            if created_any:
                await self._reorder_to_enum()

            await self.uow.commit()

    async def _reorder_to_enum(self) -> None:
        order = {gateway_type: i for i, gateway_type in enumerate(PaymentGatewayType, start=1)}

        for gateway in await self.gateway_dao.get_all():
            desired_index = order[gateway.type]
            if gateway.order_index != desired_index:
                gateway.order_index = desired_index
                await self.gateway_dao.update(gateway)


@dataclass(frozen=True)
class CreatePaymentDto:
    plan_snapshot: PlanSnapshotDto
    pricing: PriceDetailsDto
    purchase_type: PurchaseType
    gateway_type: PaymentGatewayType


class CreatePayment(Interactor[CreatePaymentDto, PaymentResultDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        uow: UnitOfWork,
        payment_gateway_dao: PaymentGatewayDao,
        transaction_dao: TransactionDao,
        get_payment_gateway_instance: GetPaymentGatewayInstance,
        translator_hub: TranslatorHub,
    ) -> None:
        self.uow = uow
        self.payment_gateway_dao = payment_gateway_dao
        self.transaction_dao = transaction_dao
        self.get_payment_gateway_instance = get_payment_gateway_instance
        self.translator_hub = translator_hub

    async def _execute(self, actor: UserDto, data: CreatePaymentDto) -> PaymentResultDto:
        gateway_instance = await self.get_payment_gateway_instance.system(data.gateway_type)
        i18n = self.translator_hub.get_translator_by_locale(actor.language)

        key, kw = i18n_format_days(data.plan_snapshot.duration)
        details = i18n.get(
            "payment-invoice-description",
            purchase_type=data.purchase_type,
            name=i18n.get(data.plan_snapshot.name),
            duration=i18n.get(key, **kw),
        )

        if data.pricing.is_free:
            async with self.uow:
                existing = await self.transaction_dao.get_recent_pending(
                    user_id=actor.id,
                    plan_id=data.plan_snapshot.id,
                    duration_days=data.plan_snapshot.duration,
                    gateway_type=gateway_instance.data.type,
                )
                if existing is not None:
                    logger.info(
                        f"Reusing pending transaction '{existing.payment_id}' "
                        f"for user '{actor.remna_name}'"
                    )
                    return PaymentResultDto(id=existing.payment_id, url=None)

                transaction = TransactionDto(
                    payment_id=uuid.uuid4(),
                    user_id=actor.id,
                    status=TransactionStatus.PENDING,
                    purchase_type=data.purchase_type,
                    gateway_type=gateway_instance.data.type,
                    pricing=data.pricing,
                    currency=gateway_instance.data.currency,
                    plan_snapshot=data.plan_snapshot,
                )
                await self.transaction_dao.create(transaction)
                await self.uow.commit()

            logger.info(
                f"Payment for user '{actor.remna_name}' not created because pricing is free"
            )
            return PaymentResultDto(id=transaction.payment_id, url=None)

        transaction = TransactionDto(
            payment_id=uuid.uuid4(),
            user_id=actor.id,
            status=TransactionStatus.PENDING,
            purchase_type=data.purchase_type,
            gateway_type=gateway_instance.data.type,
            gateway_display_name=(
                gateway_instance.data.settings.display_name
                if gateway_instance.data.settings
                else None
            ),
            pricing=data.pricing,
            currency=gateway_instance.data.currency,
            plan_snapshot=data.plan_snapshot,
        )

        async with self.uow:
            payment: PaymentResultDto = await gateway_instance.handle_create_payment(
                amount=data.pricing.final_amount,
                details=details,
            )

            transaction.payment_id = payment.id
            await self.transaction_dao.create(transaction)
            await self.uow.commit()

        logger.info(f"Created transaction '{payment.id}' for user {actor.log}")
        return payment


class CreateTestPayment(Interactor[PaymentGatewayType, PaymentResultDto]):
    required_permission = Permission.REMNASHOP_GATEWAYS

    def __init__(
        self,
        uow: UnitOfWork,
        payment_gateway_dao: PaymentGatewayDao,
        transaction_dao: TransactionDao,
        get_payment_gateway_instance: GetPaymentGatewayInstance,
        translator_hub: TranslatorHub,
    ) -> None:
        self.uow = uow
        self.payment_gateway_dao = payment_gateway_dao
        self.transaction_dao = transaction_dao
        self.get_payment_gateway_instance = get_payment_gateway_instance
        self.translator_hub = translator_hub

    async def _execute(self, actor: UserDto, gateway_type: PaymentGatewayType) -> PaymentResultDto:
        gateway_instance = await self.get_payment_gateway_instance.system(gateway_type)
        i18n = self.translator_hub.get_translator_by_locale(actor.language)

        test_pricing = PriceDetailsDto.test()
        test_plan_snapshot = PlanSnapshotDto.test()

        payment: PaymentResultDto = await gateway_instance.handle_create_payment(
            amount=test_pricing.final_amount,
            details=i18n.get("test-payment"),
        )

        async with self.uow:
            transaction = TransactionDto(
                payment_id=payment.id,
                user_id=actor.id,
                status=TransactionStatus.PENDING,
                is_test=True,
                purchase_type=PurchaseType.NEW,
                gateway_type=gateway_instance.data.type,
                gateway_display_name=(
                    gateway_instance.data.settings.display_name
                    if gateway_instance.data.settings
                    else None
                ),
                pricing=test_pricing,
                currency=gateway_instance.data.currency,
                plan_snapshot=test_plan_snapshot,
            )
            await self.transaction_dao.create(transaction)
            await self.uow.commit()

        logger.info(f"Created test transaction '{payment.id}' for user {actor.log}")
        return payment


@dataclass(frozen=True)
class ProcessPaymentDto:
    payment_id: UUID
    new_transaction_status: TransactionStatus
    gateway_type: PaymentGatewayType


class ProcessPayment(Interactor[ProcessPaymentDto, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        transaction_dao: TransactionDao,
        subscription_dao: SubscriptionDao,
        referral_dao: ReferralDao,
        event_publisher: EventPublisher,
        notifier: Notifier,
        redirect: Redirect,
        assign_referral_rewards: AssignReferralRewards,
        purchase_subscription: PurchaseSubscription,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.transaction_dao = transaction_dao
        self.subscription_dao = subscription_dao
        self.referral_dao = referral_dao
        self.event_publisher = event_publisher
        self.notifier = notifier
        self.redirect = redirect
        self.assign_referral_rewards = assign_referral_rewards
        self.purchase_subscription = purchase_subscription

    async def _execute(self, actor: UserDto, data: ProcessPaymentDto) -> None:
        payment_id = data.payment_id
        new_status = data.new_transaction_status

        async with self.uow:
            transaction = await self.transaction_dao.get_by_payment_id(payment_id)

            if not transaction:
                logger.critical(f"Transaction not found for '{payment_id}'")
                return

            if transaction.gateway_type != data.gateway_type:
                logger.error(
                    f"Gateway mismatch for transaction '{payment_id}': "
                    f"expected '{transaction.gateway_type}', got '{data.gateway_type}'"
                )
                return

            user = await self.user_dao.get_by_id(transaction.user_id)

            if not user:
                logger.critical(f"User not found for transaction '{payment_id}'")
                return

            if new_status == TransactionStatus.CANCELED:
                updated = await self.transaction_dao.transition_status(
                    payment_id,
                    TransactionStatus.CANCELED,
                    (TransactionStatus.PENDING,),
                )
                if not updated:
                    logger.warning(
                        f"Cancel transition did not match for '{payment_id}', "
                        f"user '{user.remna_name}' — already transitioned"
                    )
                    return
                await self.uow.commit()
                logger.info(f"Payment canceled '{payment_id}' for user {user.log}")
                return

            elif new_status == TransactionStatus.COMPLETED:
                updated = await self.transaction_dao.transition_status(
                    payment_id,
                    TransactionStatus.COMPLETED,
                    (TransactionStatus.PENDING, TransactionStatus.FAILED),
                )
                if not updated:
                    logger.warning(
                        f"Completed transition did not match for '{payment_id}', "
                        f"user '{user.remna_name}' — already transitioned"
                    )
                    return
                await self.uow.commit()

            elif new_status == TransactionStatus.REFUNDED:
                updated = await self.transaction_dao.transition_status(
                    payment_id,
                    TransactionStatus.REFUNDED,
                    (TransactionStatus.COMPLETED,),
                )
                if not updated:
                    logger.warning(
                        f"Refund transition did not match for '{payment_id}', "
                        f"user '{user.remna_name}' — not in COMPLETED"
                    )
                    return
                await self.uow.commit()
                logger.warning(f"Payment refunded '{payment_id}' for user {user.log}")
                await self.notifier.notify_admins(
                    MessagePayloadDto(
                        i18n_key="event-payment.refunded",
                        i18n_kwargs={
                            "payment_id": str(payment_id),
                            "gateway_type": transaction.gateway_type,
                            "final_amount": transaction.pricing.final_amount,
                            "original_amount": transaction.pricing.original_amount,
                            "discount_percent": transaction.pricing.discount_percent,
                            "currency": transaction.currency.symbol,
                            "telegram_id": user.telegram_id or 0,
                            "username": user.username or 0,
                            "name": user.name,
                            "email": user.email,
                        },
                    )
                )
                # Subscription revocation is a separate task (out of scope here)
                return

            else:
                logger.warning(
                    f"Received unhandled transaction status '{new_status}' "
                    f"for payment '{payment_id}', user '{user.remna_name}'"
                )
                return

        # UoW closed cleanly; purchase_subscription will open its own UoW
        await self._handle_success(user, transaction)
        logger.info(f"Payment succeeded '{payment_id}' for user {user.log}")

    async def _handle_success(self, user: UserDto, transaction: TransactionDto) -> None:
        if transaction.is_test:
            await self.notifier.notify_user(user, i18n_key="ntf-gateway.test-payment-confirmed")
            return

        subscription = await self.subscription_dao.get_current(user.id)
        old_plan = subscription.plan_snapshot if subscription else None

        event = UserPurchaseEvent(
            user_id=user.id,
            telegram_id=user.telegram_id,
            name=user.name,
            email=user.email,
            username=user.username,
            #
            purchase_type=transaction.purchase_type,
            is_trial_plan=transaction.plan_snapshot.is_trial,
            payment_id=transaction.payment_id,
            gateway_type=transaction.gateway_type,
            final_amount=transaction.pricing.final_amount,
            discount_percent=transaction.pricing.discount_percent,
            original_amount=transaction.pricing.original_amount,
            currency=transaction.currency.symbol,
            #
            plan_name=(transaction.plan_snapshot.name, {}),
            plan_type=transaction.plan_snapshot.type,
            plan_traffic_limit=i18n_format_traffic_limit(transaction.plan_snapshot.traffic_limit),
            plan_device_limit=i18n_format_device_limit(transaction.plan_snapshot.device_limit),
            plan_duration=i18n_format_days(transaction.plan_snapshot.duration),
            #
            previous_plan_name=(old_plan.name, {}) if old_plan else "N/A",
            previous_plan_type={
                "key": "plan-type",
                "plan_type": old_plan.type if old_plan else "N/A",
            },
            previous_plan_traffic_limit=i18n_format_traffic_limit(old_plan.traffic_limit)
            if old_plan
            else "N/A",
            previous_plan_device_limit=i18n_format_device_limit(old_plan.device_limit)
            if old_plan
            else "N/A",
            previous_plan_duration=i18n_format_days(old_plan.duration) if old_plan else "N/A",
        )

        try:
            await self.purchase_subscription.system(
                PurchaseSubscriptionDto(user, transaction, subscription)
            )
        except Exception as e:
            logger.exception(
                f"Failed to process purchase for user '{user.remna_name}', "
                f"transaction '{transaction.payment_id}'"
            )
            async with self.uow:  # fresh UoW, no nesting
                await self.transaction_dao.update_status(
                    transaction.payment_id, TransactionStatus.FAILED
                )
                await self.uow.commit()
            await self.notifier.notify_system(
                MessagePayloadDto(
                    i18n_key="event-payment.purchase-failed",
                    i18n_kwargs={
                        "payment_id": str(transaction.payment_id),
                        "gateway_type": transaction.gateway_type,
                        "final_amount": transaction.pricing.final_amount,
                        "original_amount": transaction.pricing.original_amount,
                        "discount_percent": transaction.pricing.discount_percent,
                        "currency": transaction.currency.symbol,
                        "telegram_id": user.telegram_id or 0,
                        "username": user.username or 0,
                        "name": user.name,
                        "email": user.email,
                    },
                ),
                roles=[Role.OWNER, Role.DEV],
                notification_type=SystemNotificationType.SYSTEM,
            )
            if user.telegram_id is not None:
                await self.redirect.to_failed_payment(user.telegram_id)
            raise PurchaseError(e)

        await self.event_publisher.publish(event)

        if not transaction.pricing.is_free:
            # The purchase is already COMPLETED and committed. Referral rewards are
            # best-effort: their failure must not break the successful purchase nor
            # leave the transaction in a non-terminal state for retry. Isolate it.
            try:
                await self.assign_referral_rewards.system(
                    AssignReferralRewardsDto(user, transaction)
                )
            except Exception:
                logger.exception(
                    f"Referral reward assignment failed for user '{user.remna_name}', "
                    f"transaction '{transaction.payment_id}' — purchase succeeded"
                )
                await self.notifier.notify_admins(
                    MessagePayloadDto(
                        i18n_key="event-payment.referral-failed",
                        i18n_kwargs={
                            "payment_id": str(transaction.payment_id),
                            "gateway_type": transaction.gateway_type,
                            "final_amount": transaction.pricing.final_amount,
                            "original_amount": transaction.pricing.original_amount,
                            "discount_percent": transaction.pricing.discount_percent,
                            "currency": transaction.currency.symbol,
                            "telegram_id": user.telegram_id or 0,
                            "username": user.username or 0,
                            "name": user.name,
                            "email": user.email,
                        },
                    )
                )

        if user.telegram_id is not None:
            await self.redirect.to_success_payment(user.telegram_id, transaction.purchase_type)


class RetryFailedTransaction(Interactor[UUID, None]):
    required_permission = Permission.USER_SUBSCRIPTION_EDITOR

    def __init__(
        self,
        transaction_dao: TransactionDao,
        process_payment: ProcessPayment,
    ) -> None:
        self.transaction_dao = transaction_dao
        self.process_payment = process_payment

    async def _execute(self, actor: UserDto, payment_id: UUID) -> None:
        transaction = await self.transaction_dao.get_by_payment_id(payment_id)

        if not transaction:
            raise ValueError(f"Transaction not found for '{payment_id}'")

        if transaction.status != TransactionStatus.FAILED:
            raise TransactionNotRetryableError(
                f"Transaction '{payment_id}' is not FAILED (status '{transaction.status}')"
            )

        logger.info(
            f"{actor.log} Retrying failed transaction '{payment_id}' "
            f"for user '{transaction.user_id}'"
        )

        await self.process_payment.system(
            ProcessPaymentDto(
                payment_id=payment_id,
                new_transaction_status=TransactionStatus.COMPLETED,
                gateway_type=transaction.gateway_type,
            )
        )

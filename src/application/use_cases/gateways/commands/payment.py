import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
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
from src.application.common.dao.payment_operation import PaymentOperationRecoveryMode
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
from src.application.services.payment_idempotency import PaymentIdempotencyService
from src.application.services.payment_recovery_snapshot import (
    build_payment_response,
    build_resolved_payment_snapshot,
)
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
    TransactionFulfillmentStatus,
    TransactionStatus,
)
from src.core.exceptions import PurchaseError, TransactionNotRetryableError
from src.core.utils.i18n_helpers import (
    i18n_format_days,
    i18n_format_device_limit,
    i18n_format_traffic_limit,
)
from src.core.utils.payment_methods import normalize_platega_payment_method

FULFILLMENT_LEASE = timedelta(minutes=30)


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
    provider_idempotency_key: Optional[str] = None
    payment_operation_id: Optional[int] = None
    return_url: Optional[str] = None


class CreatePayment(Interactor[CreatePaymentDto, PaymentResultDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        uow: UnitOfWork,
        payment_gateway_dao: PaymentGatewayDao,
        transaction_dao: TransactionDao,
        get_payment_gateway_instance: GetPaymentGatewayInstance,
        translator_hub: TranslatorHub,
        payment_idempotency: PaymentIdempotencyService,
    ) -> None:
        self.uow = uow
        self.payment_gateway_dao = payment_gateway_dao
        self.transaction_dao = transaction_dao
        self.get_payment_gateway_instance = get_payment_gateway_instance
        self.translator_hub = translator_hub
        self.payment_idempotency = payment_idempotency

    async def _execute(  # noqa: C901
        self, actor: UserDto, data: CreatePaymentDto
    ) -> PaymentResultDto:
        gateway_instance = await self.get_payment_gateway_instance.system(data.gateway_type)
        i18n = self.translator_hub.get_translator_by_locale(actor.language)

        key, kw = i18n_format_days(data.plan_snapshot.duration)
        details = i18n.get(
            "payment-invoice-description",
            purchase_type=data.purchase_type,
            name=i18n.get_or_raw(data.plan_snapshot.name),
            duration=i18n.get(key, **kw),
        )

        operation_id = data.payment_operation_id
        provider_key = data.provider_idempotency_key
        if (operation_id is None) != (provider_key is None):
            raise ValueError("Payment operation id and provider key must be supplied together")

        if data.pricing.is_free and operation_id is None:
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

        deterministic_payment_id = (
            UUID(provider_key) if data.pricing.is_free and provider_key else None
        )
        transaction = TransactionDto(
            payment_id=deterministic_payment_id or uuid.uuid4(),
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

        if data.pricing.is_free:
            provider_request = {
                "version": 1,
                "kind": "LOCAL",
                "payment_id": str(transaction.payment_id),
            }
            recovery_mode = PaymentOperationRecoveryMode.LOCAL
            provider_owner_hash = None
            replay_for = None
        else:
            provider_request = await gateway_instance.build_payment_request(
                data.pricing.final_amount,
                details,
                return_url=data.return_url,
            )
            if data.gateway_type == PaymentGatewayType.YOOKASSA:
                if operation_id is not None:
                    provider_request["metadata"] = {
                        "remnashop_operation_id": str(operation_id),
                    }
                recovery_mode = PaymentOperationRecoveryMode.YOOKASSA_REPLAY
                provider_owner_hash = gateway_instance.payment_owner_fingerprint()
                if not provider_owner_hash:
                    raise RuntimeError("YooKassa owner fingerprint is unavailable")
                replay_for = timedelta(hours=23)
            else:
                recovery_mode = PaymentOperationRecoveryMode.MANUAL_REQUIRED
                provider_owner_hash = gateway_instance.payment_owner_fingerprint()
                replay_for = None

        if operation_id is not None:
            await self.payment_idempotency.mark_processing(
                operation_id,
                gateway_type=data.gateway_type.value,
                resolved_payment_snapshot=build_resolved_payment_snapshot(transaction),
                provider_request_snapshot=provider_request,
                provider_owner_hash=provider_owner_hash,
                recovery_mode=recovery_mode,
                provider_replay_for=replay_for,
            )

        if data.pricing.is_free:
            payment = PaymentResultDto(id=transaction.payment_id, url=None)
        else:
            payment = await gateway_instance.create_payment_from_request(
                provider_request,
                idempotency_key=provider_key or str(uuid.uuid4()),
            )
            transaction.payment_id = payment.id

        if operation_id is not None:
            await self.payment_idempotency.checkpoint_provider_result(
                operation_id,
                {
                    "version": 1,
                    "payment_id": str(payment.id),
                    "payment_url": payment.url,
                    "provider_status": "LOCAL" if data.pricing.is_free else payment.provider_status,
                },
            )
            if not data.pricing.is_free and payment.provider_status in {"succeeded", "canceled"}:
                raise RuntimeError(
                    "Provider returned a terminal status before the local transaction existed"
                )

        async with self.uow:
            created_transaction = await self.transaction_dao.create(transaction)
            if operation_id is not None:
                await self.payment_idempotency.link_transaction(
                    operation_id,
                    created_transaction.id,
                )
                if not data.pricing.is_free:
                    await self.payment_idempotency.complete_in_current_transaction(
                        operation_id,
                        build_payment_response(created_transaction, payment_url=payment.url),
                    )
            await self.uow.commit()

        if data.pricing.is_free:
            logger.info(
                f"Payment for user '{actor.remna_name}' not created because pricing is free"
            )
        else:
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
    selected_payment_method: Optional[str] = None


class PaymentTransactionNotReadyError(Exception): ...


class PaymentEventNotAppliedError(Exception): ...


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

    async def _execute(  # noqa: C901
        self, actor: UserDto, data: ProcessPaymentDto
    ) -> None:
        payment_id = data.payment_id
        new_status = data.new_transaction_status
        fulfillment_token_hash: Optional[str] = None
        manual_escalation: Optional[tuple[UserDto, TransactionDto]] = None
        refund_notification: Optional[tuple[UserDto, TransactionDto]] = None
        payment_method_conflict = False

        async with self.uow:
            transaction = await self.transaction_dao.get_by_payment_id(payment_id)

            if not transaction:
                if new_status in {
                    TransactionStatus.COMPLETED,
                    TransactionStatus.CANCELED,
                    TransactionStatus.REFUNDED,
                }:
                    await self.transaction_dao.store_webhook_event(
                        payment_id=payment_id,
                        gateway_type=data.gateway_type,
                        status=new_status,
                        selected_payment_method=data.selected_payment_method,
                    )
                    await self.uow.commit()
                    logger.warning(
                        f"Stored early payment webhook for missing transaction '{payment_id}'"
                    )
                    raise PaymentTransactionNotReadyError
                else:
                    logger.critical(f"Transaction not found for '{payment_id}'")
                return

            if transaction.gateway_type != data.gateway_type:
                logger.error(
                    f"Gateway mismatch for transaction '{payment_id}': "
                    f"expected '{transaction.gateway_type}', got '{data.gateway_type}'"
                )
                raise PaymentEventNotAppliedError("Payment gateway mismatch")

            if data.selected_payment_method is not None:
                if data.gateway_type != PaymentGatewayType.PLATEGA:
                    raise PaymentEventNotAppliedError(
                        "Payment method metadata is only valid for Platega"
                    )
                try:
                    selected_payment_method = normalize_platega_payment_method(
                        data.selected_payment_method
                    )
                except ValueError as exc:
                    raise PaymentEventNotAppliedError(
                        "Invalid Platega payment method metadata"
                    ) from exc
                if selected_payment_method is None:
                    raise PaymentEventNotAppliedError("Empty Platega payment method metadata")
                method_applied = await self.transaction_dao.set_payment_method_if_absent_or_equal(
                    payment_id,
                    payment_method=selected_payment_method,
                )
                if not method_applied:
                    payment_method_conflict = True
                    logger.critical(
                        "Platega payment method metadata conflicts for '{}'",
                        payment_id,
                    )
                else:
                    transaction.payment_method = selected_payment_method

            user = await self.user_dao.get_by_id(transaction.user_id)

            if not user:
                logger.critical(f"User not found for transaction '{payment_id}'")
                raise PaymentEventNotAppliedError("Payment owner is unavailable")

            if new_status == TransactionStatus.CANCELED:
                updated = await self.transaction_dao.cancel_by_provider(payment_id)
                if not updated:
                    refreshed = await self.transaction_dao.get_by_payment_id(payment_id)
                    if refreshed is not None and (
                        (
                            refreshed.status == TransactionStatus.CANCELED
                            and refreshed.cancellation_reason == "PROVIDER"
                        )
                        or refreshed.status == TransactionStatus.REFUNDED
                    ):
                        logger.info(
                            f"Cancel event already terminal for '{payment_id}', "
                            f"user '{user.remna_name}'"
                        )
                        if payment_method_conflict:
                            raise PaymentEventNotAppliedError(
                                "Platega payment method conflicts with transaction state"
                            )
                        return
                    logger.warning(
                        f"Cancel transition did not match for '{payment_id}', "
                        f"user '{user.remna_name}' — already transitioned"
                    )
                    raise PaymentEventNotAppliedError(
                        "Cancel event conflicts with transaction state"
                    )
                await self.uow.commit()
                logger.info(f"Payment canceled '{payment_id}' for user {user.log}")
                if payment_method_conflict:
                    raise PaymentEventNotAppliedError(
                        "Platega payment method conflicts with transaction state"
                    )
                return

            if new_status == TransactionStatus.COMPLETED:
                token = secrets.token_urlsafe(32)
                fulfillment_token_hash = hashlib.sha256(
                    f"remnashop:fulfillment:v1\0{token}".encode()
                ).hexdigest()
                claimed = await self.transaction_dao.claim_fulfillment(
                    payment_id,
                    token_hash=fulfillment_token_hash,
                    lease_for=FULFILLMENT_LEASE,
                )
                if claimed is None:
                    refreshed = await self.transaction_dao.get_by_payment_id(payment_id)
                    if (
                        refreshed is not None
                        and refreshed.fulfillment_status == TransactionFulfillmentStatus.PROCESSING
                    ):
                        expired = await self.transaction_dao.expire_fulfillment(payment_id)
                        if expired:
                            manual_escalation = (user, refreshed)
                            await self.uow.commit()
                    elif (
                        refreshed is not None
                        and refreshed.fulfillment_status == TransactionFulfillmentStatus.SUCCEEDED
                        and refreshed.fulfillment_completed_at is not None
                    ):
                        logger.info(
                            f"Payment fulfillment already completed for '{payment_id}', "
                            f"user '{user.remna_name}'"
                        )
                    elif (
                        refreshed is not None
                        and refreshed.fulfillment_status
                        == TransactionFulfillmentStatus.MANUAL_REQUIRED
                    ):
                        logger.critical(
                            f"Payment fulfillment requires manual review for '{payment_id}', "
                            f"user '{user.remna_name}'"
                        )
                        raise PaymentEventNotAppliedError(
                            "Success event requires manual fulfillment review"
                        )
                    elif refreshed is not None and refreshed.status == TransactionStatus.REFUNDED:
                        logger.info(
                            f"Success event superseded by refund for '{payment_id}', "
                            f"user '{user.remna_name}'"
                        )
                        if payment_method_conflict:
                            raise PaymentEventNotAppliedError(
                                "Platega payment method conflicts with transaction state"
                            )
                        return
                    else:
                        logger.warning(
                            f"Completed transition did not match for '{payment_id}', "
                            f"user '{user.remna_name}' — already transitioned"
                        )
                    if manual_escalation is None and (
                        refreshed is not None
                        and refreshed.fulfillment_status
                        in {
                            TransactionFulfillmentStatus.PROCESSING,
                            TransactionFulfillmentStatus.SUCCEEDED,
                        }
                    ):
                        if payment_method_conflict:
                            raise PaymentEventNotAppliedError(
                                "Platega payment method conflicts with transaction state"
                            )
                        return
                    if manual_escalation is None:
                        raise PaymentEventNotAppliedError(
                            "Success event conflicts with transaction state"
                        )
                else:
                    transaction = claimed
                    user = await self.user_dao.get_by_id(transaction.user_id)
                    if user is None:
                        raise RuntimeError("Claimed payment owner is unavailable")
                    await self.uow.commit()

            elif new_status == TransactionStatus.REFUNDED:
                updated = await self.transaction_dao.transition_refunded(payment_id)
                if not updated:
                    manual = await self.transaction_dao.mark_refund_manual_required(payment_id)
                    if manual:
                        refreshed = await self.transaction_dao.get_by_payment_id(payment_id)
                        if refreshed is None:
                            raise RuntimeError("Refunded transaction disappeared")
                        if (
                            refreshed.fulfillment_status
                            == TransactionFulfillmentStatus.MANUAL_REQUIRED
                        ):
                            manual_escalation = (user, refreshed)
                        else:
                            refund_notification = (user, refreshed)
                        await self.uow.commit()
                    else:
                        refreshed = await self.transaction_dao.get_by_payment_id(payment_id)
                        if refreshed is not None and refreshed.status == TransactionStatus.REFUNDED:
                            if (
                                refreshed.fulfillment_status
                                == TransactionFulfillmentStatus.MANUAL_REQUIRED
                                and refreshed.fulfillment_alerted_at is None
                            ):
                                manual_escalation = (user, refreshed)
                            else:
                                refund_notification = (user, refreshed)
                            await self.uow.commit()
                        else:
                            logger.warning(
                                f"Refund transition did not match for '{payment_id}', "
                                f"user '{user.remna_name}' — fulfillment is not proven"
                            )
                            raise PaymentEventNotAppliedError(
                                "Refund event conflicts with transaction state"
                            )
                else:
                    await self.uow.commit()
                    logger.warning(f"Payment refunded '{payment_id}' for user {user.log}")
                    refund_notification = (user, updated)

            else:
                logger.warning(
                    f"Received unhandled transaction status '{new_status}' "
                    f"for payment '{payment_id}', user '{user.remna_name}'"
                )
                raise PaymentEventNotAppliedError("Unhandled payment event status")

        if manual_escalation is not None:
            await self._notify_ambiguous_fulfillment(*manual_escalation)
            if payment_method_conflict:
                raise PaymentEventNotAppliedError(
                    "Platega payment method conflicts with transaction state"
                )
            return

        if refund_notification is not None:
            await self._notify_refund(*refund_notification)
            if payment_method_conflict:
                raise PaymentEventNotAppliedError(
                    "Platega payment method conflicts with transaction state"
                )
            return

        if fulfillment_token_hash is None:
            raise RuntimeError("Payment fulfillment token was not established")

        # The external subscription operation is intentionally outside the claim
        # transaction. The durable PROCESSING state prevents an ambiguous retry.
        try:
            await self._handle_success(user, transaction)
        except Exception as exc:
            async with self.uow:
                marked_manual = await self.transaction_dao.mark_fulfillment_manual_required(
                    payment_id,
                    token_hash=fulfillment_token_hash,
                    error_code="FULFILLMENT_SIDE_EFFECT_FAILED",
                )
                if not marked_manual:
                    refreshed = await self.transaction_dao.get_by_payment_id(payment_id)
                    if (
                        refreshed is None
                        or refreshed.fulfillment_status
                        != TransactionFulfillmentStatus.MANUAL_REQUIRED
                    ):
                        raise RuntimeError(
                            "Payment fulfillment failure could not be fenced"
                        ) from exc
                await self.uow.commit()
            raise
        async with self.uow:
            marked = await self.transaction_dao.complete_fulfillment(
                payment_id,
                token_hash=fulfillment_token_hash,
            )
            if not marked:
                refreshed = await self.transaction_dao.get_by_payment_id(payment_id)
                if (
                    refreshed is not None
                    and refreshed.status == TransactionStatus.REFUNDED
                    and refreshed.fulfillment_status
                    in {
                        TransactionFulfillmentStatus.PROCESSING,
                        TransactionFulfillmentStatus.MANUAL_REQUIRED,
                    }
                    and refreshed.fulfillment_completed_at is None
                ):
                    finalized = await self.transaction_dao.mark_fulfillment_manual_required(
                        payment_id,
                        token_hash=fulfillment_token_hash,
                        error_code="REFUND_DURING_COMPLETED_SIDE_EFFECT",
                    )
                    if not finalized:
                        raise RuntimeError(
                            "Refunded payment fulfillment could not release its fence"
                        )
                    refreshed = await self.transaction_dao.get_by_payment_id(payment_id)
                    if refreshed is None:
                        raise RuntimeError("Refunded payment fulfillment disappeared")
                    manual_escalation = (user, refreshed)
                elif (
                    refreshed is not None
                    and refreshed.fulfillment_token_hash == fulfillment_token_hash
                    and refreshed.fulfillment_status
                    in {
                        TransactionFulfillmentStatus.PROCESSING,
                        TransactionFulfillmentStatus.MANUAL_REQUIRED,
                    }
                    and refreshed.fulfillment_completed_at is None
                ):
                    finalized = await self.transaction_dao.mark_fulfillment_manual_required(
                        payment_id,
                        token_hash=fulfillment_token_hash,
                        error_code="FULFILLMENT_RESULT_AFTER_LEASE",
                    )
                    if not finalized:
                        raise RuntimeError(
                            "Expired payment fulfillment could not preserve its fence"
                        )
                    refreshed = await self.transaction_dao.get_by_payment_id(payment_id)
                    if refreshed is None:
                        raise RuntimeError("Expired payment fulfillment disappeared")
                    manual_escalation = (user, refreshed)
                if manual_escalation is None and (
                    refreshed is None
                    or refreshed.fulfillment_status != TransactionFulfillmentStatus.SUCCEEDED
                    or refreshed.fulfillment_completed_at is None
                ):
                    raise RuntimeError("Payment fulfillment proof could not be persisted")
            await self.uow.commit()
        if manual_escalation is not None:
            await self._notify_ambiguous_fulfillment(*manual_escalation)
            if payment_method_conflict:
                raise PaymentEventNotAppliedError(
                    "Platega payment method conflicts with transaction state"
                )
            return
        logger.info(f"Payment succeeded '{payment_id}' for user {user.log}")
        if payment_method_conflict:
            raise PaymentEventNotAppliedError(
                "Platega payment method conflicts with transaction state"
            )

    async def _notify_refund(
        self,
        user: UserDto,
        transaction: TransactionDto,
    ) -> None:
        await self.notifier.notify_admins(
            MessagePayloadDto(
                i18n_key="event-payment.refunded",
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
        # Subscription revocation is a separate task (out of scope here).

    async def _notify_ambiguous_fulfillment(
        self,
        user: UserDto,
        transaction: TransactionDto,
    ) -> None:
        logger.critical(
            f"Payment fulfillment lease expired without proof for "
            f"'{transaction.payment_id}', user '{user.remna_name}'"
        )
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
        async with self.uow:
            await self.transaction_dao.mark_fulfillment_alerted(transaction.payment_id)
            await self.uow.commit()

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
            # Plan names are operator-owned display text, not Fluent keys.
            plan_name=transaction.plan_snapshot.name,
            plan_type=transaction.plan_snapshot.type,
            plan_traffic_limit=i18n_format_traffic_limit(transaction.plan_snapshot.traffic_limit),
            plan_device_limit=i18n_format_device_limit(transaction.plan_snapshot.device_limit),
            plan_duration=i18n_format_days(transaction.plan_snapshot.duration),
            #
            previous_plan_name=old_plan.name if old_plan else "N/A",
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
            # Persist immutable reward intents while this transaction still owns the
            # fulfillment fence. Issuance is asynchronous and begins only after the
            # source transaction is durably SUCCEEDED.
            await self.assign_referral_rewards.system(AssignReferralRewardsDto(user, transaction))

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

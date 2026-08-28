from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.types import Message, PreCheckoutQuery
from dishka import FromDishka
from loguru import logger

from src.application.dto import TelegramUserDto
from src.application.use_cases.gateways.commands.payment import ProcessPayment, ProcessPaymentDto
from src.core.enums import PaymentGatewayType, TransactionStatus

router = Router(name=__name__)


@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery, user: TelegramUserDto) -> None:
    logger.info(f"{user.log} Initiated a pre-checkout query")
    if pre_checkout_query.invoice_payload:
        await pre_checkout_query.answer(ok=True)
    else:
        logger.warning(f"{user.log} Pre-checkout query rejected: empty payload")
        await pre_checkout_query.answer(ok=False)


@router.message(F.successful_payment)
async def on_successful_payment(
    message: Message,
    user: TelegramUserDto,
    bot: Bot,
    process_payment: FromDishka[ProcessPayment],
) -> None:
    payment = message.successful_payment

    if not payment:
        return

    new_status = TransactionStatus.COMPLETED
    if user.is_owner:
        # Refund the owner's test charge, but process the transaction as completed.
        # Using CANCELED here prevents ProcessPayment from applying the purchased plan.
        logger.info(
            f"{user.log} Refunding owner test payment "
            f"'{payment.telegram_payment_charge_id}' while completing the transaction"
        )
        await bot.refund_star_payment(
            user_id=user.telegram_id,
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
        )
    await process_payment.system(
        ProcessPaymentDto(
            payment_id=UUID(payment.invoice_payload),
            new_transaction_status=new_status,
            gateway_type=PaymentGatewayType.TELEGRAM_STARS,
        )
    )

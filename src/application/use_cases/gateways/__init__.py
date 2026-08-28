from typing import Final

from src.application.common.interactor import Interactor

from .commands.configuration import (
    MovePaymentGatewayUp,
    ResetPaymentGatewaySettingsField,
    TogglePaymentGatewayActive,
    UpdatePaymentGatewaySettings,
)
from .commands.payment import (
    CreateDefaultPaymentGateway,
    CreatePayment,
    CreateTestPayment,
    ProcessPayment,
    RetryFailedTransaction,
)
from .queries.providers import GetPaymentGatewayInstance
from .queries.stars import IsStarsPaymentBlocked

GATEWAYS_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    GetPaymentGatewayInstance,
    IsStarsPaymentBlocked,
    MovePaymentGatewayUp,
    TogglePaymentGatewayActive,
    UpdatePaymentGatewaySettings,
    ResetPaymentGatewaySettingsField,
    CreateDefaultPaymentGateway,
    CreatePayment,
    CreateTestPayment,
    ProcessPayment,
    RetryFailedTransaction,
)

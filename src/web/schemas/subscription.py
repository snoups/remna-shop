from datetime import datetime
from typing import Literal, Optional

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from src.core.enums import PaymentGatewayType


class SubscriptionInfoResponse(BaseModel):
    user_remna_id: str
    status: str
    is_trial: bool
    traffic_limit: int
    device_limit: int
    traffic_limit_strategy: str
    expire_at: datetime
    url: str
    plan_name: str
    plan_duration_days: int
    used_traffic_bytes: Optional[int] = None
    lifetime_used_traffic_bytes: Optional[int] = None
    online_at: Optional[datetime] = None


class DeviceResponse(BaseModel):
    hwid: str
    platform: Optional[str] = None
    device_model: Optional[str] = None
    os_version: Optional[str] = None
    user_agent: Optional[str] = None


class DevicesResponse(BaseModel):
    devices: list[DeviceResponse]
    current_count: int
    max_count: int


class DeviceDeleteResponse(BaseModel):
    deleted: bool


class DevicesDeleteAllResponse(BaseModel):
    success: bool


class PromocodeActivateRequest(BaseModel):
    code: str


class PromocodeActivateResponse(BaseModel):
    success: bool
    reward_type: str


class TrialPurchaseRequest(BaseModel):
    gateway_type: PaymentGatewayType


class ReissueResponse(BaseModel):
    success: bool


class PurchaseRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    plan_code: str = Field(min_length=3, max_length=64)
    duration_days: int = Field(ge=0)
    gateway_type: PaymentGatewayType
    return_url: Optional[AnyHttpUrl] = None


class ExtendRequest(BaseModel):
    duration_days: int = Field(ge=0)
    gateway_type: PaymentGatewayType
    return_url: Optional[AnyHttpUrl] = None


class PaymentInitResponse(BaseModel):
    payment_id: str
    payment_url: Optional[str] = None
    purchase_type: str
    status: str
    is_free: bool
    final_amount: str
    currency: str
    return_url: Optional[str] = None


class PaymentTransactionResponse(BaseModel):
    payment_id: str
    purchase_type: str
    status: str
    gateway_type: PaymentGatewayType
    final_amount: str
    currency: str
    plan_name: Optional[str] = None
    duration_days: Optional[int] = None
    device_limit: Optional[int] = None
    traffic_limit: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class PaymentTransactionsPageResponse(BaseModel):
    items: list[PaymentTransactionResponse]
    next_cursor: Optional[str] = None


class PaymentOperationResponse(BaseModel):
    operation: Literal["PURCHASE", "EXTEND"]
    state: Literal["SUCCEEDED", "IN_PROGRESS", "UNKNOWN", "MANUAL_REQUIRED"]
    payment: Optional[PaymentInitResponse] = None
    transaction: Optional[PaymentTransactionResponse] = None
    retry_after_seconds: Optional[int] = Field(default=None, ge=1, le=300)

    @model_validator(mode="after")
    def validate_state_payload(self) -> "PaymentOperationResponse":
        if self.state == "SUCCEEDED":
            if self.payment is None or self.transaction is None:
                raise ValueError("SUCCEEDED requires payment and transaction responses")
            if self.retry_after_seconds is not None:
                raise ValueError("SUCCEEDED cannot include a retry delay")
            return self

        if self.payment is not None or self.transaction is not None:
            raise ValueError("Non-success states cannot expose payment data")
        if self.state in {"IN_PROGRESS", "UNKNOWN"}:
            if self.retry_after_seconds is None:
                raise ValueError(f"{self.state} requires a retry delay")
        elif self.retry_after_seconds is not None:
            raise ValueError("MANUAL_REQUIRED cannot include a retry delay")
        return self


class TransactionCapabilitiesResponse(BaseModel):
    keyset_pagination: Literal[True] = True
    exact_lookup: Literal[True] = True
    max_page_size: Literal[100] = 100


class PaymentReconciliationCapabilitiesResponse(BaseModel):
    operation_lookup: Literal[True] = True
    user_reconcile: Literal[True] = True
    admin_reconcile: Literal[True] = True
    states: list[str] = ["SUCCEEDED", "IN_PROGRESS", "UNKNOWN", "MANUAL_REQUIRED"]
    auto_replay_gateways: list[PaymentGatewayType] = [PaymentGatewayType.YOOKASSA]


class SubscriptionCapabilitiesResponse(BaseModel):
    contract_version: Literal[1] = 1
    transactions: TransactionCapabilitiesResponse = Field(
        default_factory=TransactionCapabilitiesResponse
    )
    payment_reconciliation: PaymentReconciliationCapabilitiesResponse = Field(
        default_factory=PaymentReconciliationCapabilitiesResponse
    )


class GatewayOfferResponse(BaseModel):
    gateway_type: PaymentGatewayType
    currency: str
    currency_symbol: str


class DurationGatewayPriceResponse(BaseModel):
    gateway_type: PaymentGatewayType
    currency: str
    currency_symbol: str
    original_amount: str
    discount_percent: int
    final_amount: str
    is_free: bool


class DurationOfferResponse(BaseModel):
    days: int
    prices: list[DurationGatewayPriceResponse]


class TrialActivateResponse(BaseModel):
    is_free: bool
    activated: bool
    duration_days: int
    gateways: list[DurationGatewayPriceResponse] = []


class PlanOfferResponse(BaseModel):
    id: int
    public_code: str
    name: str
    description: Optional[str] = None
    traffic_limit: int
    device_limit: int
    type: str
    recommended_purchase_type: str
    renewal_terms_changed: bool = False
    durations: list[DurationOfferResponse]


class SubscriptionOffersResponse(BaseModel):
    gateways: list[GatewayOfferResponse]
    plans: list[PlanOfferResponse]
    has_current_subscription: bool
    current_subscription_status: Optional[str] = None

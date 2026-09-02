from datetime import datetime
from typing import Any
from uuid import UUID

from remnapy.enums.users import TrafficLimitStrategy
from sqlalchemy import ARRAY, DateTime, Enum, Integer
from sqlalchemy import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, registry

from src.core.enums import (
    BroadcastAudience,
    BroadcastMessageStatus,
    BroadcastStatus,
    Currency,
    Locale,
    PaymentGatewayType,
    PlanAvailability,
    PlanType,
    PromocodeAvailability,
    PromocodeRewardType,
    PurchaseType,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardState,
    ReferralRewardStrategy,
    ReferralRewardType,
    Role,
    SubscriptionStatus,
    TransactionFulfillmentStatus,
    TransactionStatus,
)

mapper_registry = registry(
    type_annotation_map={
        int: Integer,
        dict[str, Any]: JSONB,
        UUID: PG_UUID,
        list[UUID]: ARRAY(PG_UUID),
        datetime: DateTime(timezone=True),
        #
        Locale: Enum(Locale, name="locale"),
        Role: Enum(Role, name="user_role"),
        Currency: Enum(Currency, name="currency"),
        PaymentGatewayType: Enum(PaymentGatewayType, name="payment_gateway_type"),
        PurchaseType: Enum(PurchaseType, name="purchase_type"),
        TransactionStatus: Enum(TransactionStatus, name="transaction_status"),
        TransactionFulfillmentStatus: Enum(
            TransactionFulfillmentStatus,
            name="transaction_fulfillment_status",
        ),
        SubscriptionStatus: Enum(SubscriptionStatus, name="subscription_status"),
        TrafficLimitStrategy: Enum(TrafficLimitStrategy, name="plan_traffic_limit_strategy"),
        PlanAvailability: Enum(PlanAvailability, name="plan_availability"),
        PlanType: Enum(PlanType, name="plan_type"),
        BroadcastStatus: Enum(BroadcastStatus, name="broadcast_status"),
        BroadcastAudience: Enum(BroadcastAudience, name="broadcast_audience"),
        BroadcastMessageStatus: Enum(BroadcastMessageStatus, name="broadcast_message_status"),
        ReferralAccrualStrategy: Enum(ReferralAccrualStrategy, name="referral_accrual_strategy"),
        ReferralLevel: Enum(ReferralLevel, name="referral_level"),
        ReferralRewardStrategy: Enum(ReferralRewardStrategy, name="referral_reward_strategy"),
        ReferralRewardState: Enum(ReferralRewardState, name="referral_reward_state"),
        ReferralRewardType: Enum(ReferralRewardType, name="referral_reward_type"),
        PromocodeRewardType: Enum(PromocodeRewardType, name="promocode_reward_type"),
        PromocodeAvailability: Enum(PromocodeAvailability, name="promocode_availability"),
    }
)


class BaseSql(DeclarativeBase):
    registry = mapper_registry

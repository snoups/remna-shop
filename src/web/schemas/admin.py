from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)


class MergeUsersRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_user_id: int = Field(gt=0)
    target_user_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=1024)
    email_resolution: Literal["REJECT", "KEEP_TARGET"] = "REJECT"
    telegram_resolution: Literal["REJECT", "KEEP_SOURCE"] = "REJECT"
    payment_resolution: Literal["REJECT", "REKEY_SOURCE"] = "REJECT"


class MergeUsersTargetResponse(BaseModel):
    id: int
    email: str | None
    telegram_id: int | None
    is_email_verified: bool
    current_subscription_id: int | None


class MergeUsersResponse(BaseModel):
    dry_run: bool
    source_user_id: int
    target_user_id: int
    target: MergeUsersTargetResponse
    moved: dict[str, int]
    conflicts: list[str]
    requires_relogin: bool


class ManualReferralRewardResponse(BaseModel):
    id: int
    user_id: int
    referral_id: int
    source_transaction_id: int | None
    origin_referral_id: int | None
    level: int | None
    type: str
    amount: int
    state: str
    is_issued: bool
    last_error: str | None
    attempt_count: int
    target_subscription_id: int | None
    baseline_expire_at: datetime | None
    target_expire_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None
    manual_alerted_at: datetime | None
    refund_detected_at: datetime | None
    manual_incident_version: int
    manual_cause: str | None


class ResolveManualReferralRewardRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    resolution: Literal[
        "CONFIRM_ISSUED",
        "CANCEL",
        "ACK_ADMIN_COMPENSATED_REFUND",
    ]
    expected_version: int = Field(ge=0)
    operator_reference: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=1024)
    allow_drift: bool = False

    @model_validator(mode="after")
    def validate_refund_ack(self) -> "ResolveManualReferralRewardRequest":
        if self.resolution == "ACK_ADMIN_COMPENSATED_REFUND" and self.allow_drift:
            raise ValueError("Refund acknowledgment cannot use a drift override")
        return self


class LegacyReferralRewardRecoveryRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)

    action: Literal[
        "RETRY_PROVEN_MISSING",
        "CONFIRM_ADMIN_COMPENSATED",
        "RETRY_OPERATOR_DIRECTED",
    ]
    expected_version: StrictInt = Field(ge=0)
    source_transaction_id: StrictInt | None = Field(default=None, gt=0)
    origin_referral_id: StrictInt | None = Field(default=None, gt=0)
    level: Literal[1, 2] | None = None
    source_validation: Literal["LOCAL_COMPLETED", "PROVIDER_SUCCEEDED"] | None = None
    expected_reward_amount: StrictInt = Field(gt=0)
    accrual_strategy_snapshot: Literal["ON_FIRST_PAYMENT", "ON_EACH_PAYMENT"] | None = None
    reward_strategy: Literal["AMOUNT", "PERCENT"] | None = None
    config_value: StrictInt | None = Field(default=None, gt=0)
    operator_reference: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=1024)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_user_id: StrictInt | None = Field(default=None, gt=0)
    expected_referral_id: StrictInt | None = Field(default=None, gt=0)
    expected_created_at: datetime | None = None
    expected_participant_merge_audit_ids: list[StrictInt] = Field(
        default_factory=list,
        max_length=5000,
    )

    @field_validator("expected_created_at", mode="before")
    @classmethod
    def validate_json_timestamp(cls, value: object) -> object:
        """Accept the one canonical ISO timestamp representation available to JSON."""

        if value is None or isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            return value
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("expected_created_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.isoformat() != value:
            raise ValueError("expected_created_at must be canonical and timezone-aware")
        return parsed

    @model_validator(mode="after")
    def validate_action_evidence(self) -> "LegacyReferralRewardRecoveryRequest":
        snapshot = (
            self.accrual_strategy_snapshot,
            self.reward_strategy,
            self.config_value,
        )
        source = (self.source_transaction_id, self.origin_referral_id, self.level)
        expected_row = (
            self.expected_user_id,
            self.expected_referral_id,
            self.expected_created_at,
        )
        merge_audit_ids = self.expected_participant_merge_audit_ids
        if (
            any(audit_id <= 0 for audit_id in merge_audit_ids)
            or merge_audit_ids != sorted(set(merge_audit_ids))
        ):
            raise ValueError(
                "expected_participant_merge_audit_ids must be positive, sorted, and unique"
            )
        if self.action == "RETRY_PROVEN_MISSING":
            if any(value is None for value in (*source, *snapshot)):
                raise ValueError(
                    "RETRY_PROVEN_MISSING requires exact source and historical policy"
                )
            if (
                any(value is not None for value in expected_row)
                or self.source_validation is not None
                or merge_audit_ids
            ):
                raise ValueError("Source-backed recovery must not include operator row hints")
        elif self.action == "CONFIRM_ADMIN_COMPENSATED":
            if any(value is None for value in source):
                raise ValueError("CONFIRM_ADMIN_COMPENSATED requires exact source evidence")
            if (
                any(value is not None for value in (*snapshot, *expected_row))
                or self.source_validation is not None
                or merge_audit_ids
            ):
                raise ValueError(
                    "CONFIRM_ADMIN_COMPENSATED must not invent a historical policy snapshot"
                )
        elif (
            any(value is None for value in (*source, *expected_row))
            or any(value is not None for value in snapshot)
            or self.source_validation is None
        ):
            raise ValueError(
                "RETRY_OPERATOR_DIRECTED requires exact source/row hints and no policy"
            )
        return self


class LegacyReferralRewardRecoveryBatchItem(LegacyReferralRewardRecoveryRequest):
    reward_id: StrictInt = Field(gt=0)


class LegacyReferralRewardRecoveryBatchRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entries: list[LegacyReferralRewardRecoveryBatchItem] = Field(
        min_length=1,
        max_length=5000,
    )

    @model_validator(mode="after")
    def validate_unique_rewards(self) -> "LegacyReferralRewardRecoveryBatchRequest":
        reward_ids = [entry.reward_id for entry in self.entries]
        if len(reward_ids) != len(set(reward_ids)):
            raise ValueError("Batch reward ids must be unique")
        return self


class HistoricalReferralBackfillIntentResponse(BaseModel):
    source_transaction_id: int
    payer_user_id: int
    recipient_user_id: int
    origin_referral_id: int
    reward_referral_id: int
    level: int
    amount: int
    config_value: int
    reward_type: str
    reward_strategy: str
    accrual_strategy: str


class HistoricalReferralBackfillTransactionResponse(BaseModel):
    source_transaction_id: int
    payer_user_id: int | None
    fulfillment_completed_at: str | None
    intents: list[HistoricalReferralBackfillIntentResponse]
    errors: list[str]


class HistoricalReferralBackfillConfigSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    enabled: StrictBool
    max_level: StrictInt = Field(ge=1, le=2)
    accrual_strategy: Literal["ON_FIRST_PAYMENT", "ON_EACH_PAYMENT"]
    reward_type: Literal["POINTS", "EXTRA_DAYS"]
    reward_strategy: Literal["AMOUNT", "PERCENT"]
    reward_config: dict[Literal["1", "2"], StrictInt]

    @model_validator(mode="after")
    def validate_positive_enabled_level_config(
        self,
    ) -> "HistoricalReferralBackfillConfigSnapshot":
        allowed_keys = {str(level) for level in range(1, self.max_level + 1)}
        if not set(self.reward_config) <= allowed_keys:
            raise ValueError("reward_config contains a disabled referral level")
        if any(value <= 0 for value in self.reward_config.values()):
            raise ValueError("reward_config values must be positive strict integers")
        return self


class HistoricalReferralBackfillInventoryResponse(BaseModel):
    read_only: bool
    limit: int
    offset: int
    config_snapshot: HistoricalReferralBackfillConfigSnapshot
    candidates: list[HistoricalReferralBackfillTransactionResponse]


class HistoricalReferralBackfillPreviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_transaction_ids: list[int] = Field(min_length=1, max_length=100)
    operator_identity: str = Field(min_length=1, max_length=128)
    operator_reference: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=1024)


class HistoricalReferralBackfillPreviewResponse(BaseModel):
    preview_id: int
    status: Literal["PREVIEWED", "APPLIED"]
    source_transaction_ids: list[int]
    config_snapshot: HistoricalReferralBackfillConfigSnapshot
    can_apply: bool
    transactions: list[HistoricalReferralBackfillTransactionResponse]
    intents: list[HistoricalReferralBackfillIntentResponse]


class HistoricalReferralBackfillApplyRequest(HistoricalReferralBackfillPreviewRequest):
    expected_config_snapshot: HistoricalReferralBackfillConfigSnapshot


class HistoricalReferralBackfillApplyResponse(BaseModel):
    preview_id: int
    status: Literal["APPLIED"]
    created_intents: int
    idempotent_replay: bool

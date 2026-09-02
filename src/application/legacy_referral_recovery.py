import hashlib
import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from src.application.dto import LegacyReferralRewardRecoveryDto
from src.core.config import AppConfig
from src.core.constants import (
    PROVIDER_SUCCEEDED_REFERRAL_EVIDENCE_SHA256,
    PROVIDER_SUCCEEDED_REFERRAL_REWARD_ID,
    PROVIDER_SUCCEEDED_REFERRAL_SOURCE_TRANSACTION_ID,
)

MAX_MANIFEST_BYTES = 1024 * 1024


class LegacyReferralRecoveryAuthorizationError(ValueError):
    """The disabled or trusted one-shot recovery gate rejected a request."""


class _ManifestEntryV1(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    reward_id: StrictInt = Field(gt=0)
    action: Literal["RETRY_PROVEN_MISSING", "CONFIRM_ADMIN_COMPENSATED"]
    expected_version: Literal[1]
    source_transaction_id: StrictInt = Field(gt=0)
    origin_referral_id: StrictInt = Field(gt=0)
    level: Literal[1, 2]
    expected_reward_amount: StrictInt = Field(gt=0)
    accrual_strategy_snapshot: Literal["ON_FIRST_PAYMENT", "ON_EACH_PAYMENT"] | None
    reward_strategy: Literal["AMOUNT", "PERCENT"] | None
    config_value: StrictInt | None = Field(gt=0)
    operator_reference: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=1024)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_policy_evidence(self) -> "_ManifestEntryV1":
        policy = (
            self.accrual_strategy_snapshot,
            self.reward_strategy,
            self.config_value,
        )
        if self.action == "RETRY_PROVEN_MISSING" and any(value is None for value in policy):
            raise ValueError("RETRY_PROVEN_MISSING manifest entry requires exact policy")
        if self.action == "CONFIRM_ADMIN_COMPENSATED" and any(
            value is not None for value in policy
        ):
            raise ValueError("ADMIN manifest entry must not invent policy")
        return self


class _AdminAllocation(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    total_granted_days: StrictInt = Field(ge=0)
    allocated_days: StrictInt = Field(ge=0)
    unallocated_days: StrictInt = Field(ge=0)
    coverage_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _RecoveryManifestV1(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)

    version: Literal[1]
    incident: str = Field(min_length=1, max_length=128)
    entry_count: Literal[9]
    entries: list[_ManifestEntryV1] = Field(min_length=9, max_length=9)
    admin_compensation: _AdminAllocation

    @model_validator(mode="after")
    def validate_one_shot_allocation(self) -> "_RecoveryManifestV1":
        if self.entry_count != len(self.entries):
            raise ValueError("Manifest entry_count does not match entries")
        reward_ids = [entry.reward_id for entry in self.entries]
        if len(reward_ids) != len(set(reward_ids)):
            raise ValueError("Manifest reward ids must be unique")
        source_levels = [(entry.source_transaction_id, entry.level) for entry in self.entries]
        if len(source_levels) != len(set(source_levels)):
            raise ValueError("Manifest source/level tuples must be unique")

        allocation = self.admin_compensation
        if allocation.total_granted_days != (
            allocation.allocated_days + allocation.unallocated_days
        ):
            raise ValueError("ADMIN compensation allocation is not conserved")
        allocated_from_entries = sum(
            entry.expected_reward_amount
            for entry in self.entries
            if entry.action == "CONFIRM_ADMIN_COMPENSATED"
        )
        if allocated_from_entries != allocation.allocated_days:
            raise ValueError("ADMIN manifest entries do not match allocated days")
        retry_entries = [entry for entry in self.entries if entry.action == "RETRY_PROVEN_MISSING"]
        admin_entries = [
            entry for entry in self.entries if entry.action == "CONFIRM_ADMIN_COMPENSATED"
        ]
        if len(retry_entries) != 2 or len(admin_entries) != 7:
            raise ValueError(
                "Canonical v1 manifest requires exactly two retry and seven ADMIN entries"
            )
        if any(
            entry.evidence_sha256 != allocation.coverage_evidence_sha256 for entry in admin_entries
        ):
            raise ValueError("ADMIN entries must use the conserved FIFO coverage evidence")
        return self


class _ManifestEntryV2(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    reward_id: StrictInt = Field(gt=0)
    action: Literal["RETRY_OPERATOR_DIRECTED"]
    expected_version: Literal[1]
    source_transaction_id: StrictInt = Field(gt=0)
    origin_referral_id: StrictInt = Field(gt=0)
    level: Literal[1, 2]
    source_validation: Literal["LOCAL_COMPLETED", "PROVIDER_SUCCEEDED"]
    expected_user_id: StrictInt = Field(gt=0)
    expected_referral_id: StrictInt = Field(gt=0)
    expected_reward_amount: StrictInt = Field(gt=0)
    expected_created_at: str = Field(min_length=20, max_length=64)
    expected_participant_merge_audit_ids: list[StrictInt] = Field(
        default_factory=list,
        max_length=5000,
    )
    operator_reference: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=1024)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_canonical_timestamp(self) -> "_ManifestEntryV2":
        if (
            any(audit_id <= 0 for audit_id in self.expected_participant_merge_audit_ids)
            or self.expected_participant_merge_audit_ids
            != sorted(set(self.expected_participant_merge_audit_ids))
        ):
            raise ValueError(
                "expected_participant_merge_audit_ids must be positive, sorted, and unique"
            )
        try:
            parsed = datetime.fromisoformat(self.expected_created_at)
        except ValueError as exc:
            raise ValueError("expected_created_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.isoformat() != self.expected_created_at:
            raise ValueError("expected_created_at must be canonical and timezone-aware")
        if (
            self.source_validation == "PROVIDER_SUCCEEDED"
            and (
                self.reward_id != PROVIDER_SUCCEEDED_REFERRAL_REWARD_ID
                or self.source_transaction_id
                != PROVIDER_SUCCEEDED_REFERRAL_SOURCE_TRANSACTION_ID
                or self.evidence_sha256
                != PROVIDER_SUCCEEDED_REFERRAL_EVIDENCE_SHA256
            )
        ):
            raise ValueError("PROVIDER_SUCCEEDED requires the pinned rr65 provider evidence")
        return self


class _RecoveryManifestV2(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)

    version: Literal[2]
    incident: str = Field(min_length=1, max_length=128)
    entry_count: StrictInt = Field(gt=0, le=5000)
    entries: list[_ManifestEntryV2] = Field(min_length=1, max_length=5000)
    audit_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    allocation_rule: Literal["ADMIN_DAYS_FIFO_AFTER_REWARD"]

    @model_validator(mode="after")
    def validate_frozen_batch(self) -> "_RecoveryManifestV2":
        if self.entry_count != len(self.entries):
            raise ValueError("Manifest entry_count does not match entries")
        reward_ids = [entry.reward_id for entry in self.entries]
        if len(reward_ids) != len(set(reward_ids)):
            raise ValueError("Manifest reward ids must be unique")
        source_levels = [(entry.source_transaction_id, entry.level) for entry in self.entries]
        if len(source_levels) != len(set(source_levels)):
            raise ValueError("Manifest source/level tuples must be unique")
        if any(
            entry.source_validation == "LOCAL_COMPLETED"
            and entry.evidence_sha256 != self.audit_evidence_sha256
            for entry in self.entries
        ):
            raise ValueError("LOCAL_COMPLETED entries must use the frozen audit evidence digest")
        return self


_RecoveryManifest = _RecoveryManifestV1 | _RecoveryManifestV2


def canonical_legacy_recovery_manifest_sha256(manifest: object) -> str:
    canonical = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LegacyReferralRecoveryAuthorizationError(
                f"Trusted recovery manifest contains duplicate key '{key}'"
            )
        result[key] = value
    return result


class LegacyReferralRecoveryAuthorizer:
    """Authorize only exact entries committed by a trusted finite manifest.

    The deployment gate is disabled by default. The configured SHA-256 commits
    the canonical manifest, whose unique reward and source/level tuples form the
    one-shot allow-list. Database resolution uniqueness consumes each entry;
    exact API retries remain idempotent. Operators should disable and unmount the
    manifest immediately after the finite incident is reconciled.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._manifest: _RecoveryManifest | None = None
        if self.config.referral_reward_legacy_recovery_enabled:
            self._manifest = self._load_manifest()

    def authorize(self, recovery: LegacyReferralRewardRecoveryDto) -> str:
        manifest = self._load_manifest()
        if recovery.resolved_by != "ADMIN_API":
            raise LegacyReferralRecoveryAuthorizationError(
                "Legacy recovery resolved_by is fixed to ADMIN_API"
            )
        if recovery.action.value == "RETRY_OPERATOR_DIRECTED":
            request_entry = {
                "reward_id": recovery.reward_id,
                "action": recovery.action.value,
                "expected_version": recovery.expected_version,
                "source_transaction_id": recovery.source_transaction_id,
                "origin_referral_id": recovery.origin_referral_id,
                "level": recovery.level.value if recovery.level is not None else None,
                "source_validation": (
                    recovery.source_validation.value
                    if recovery.source_validation is not None
                    else None
                ),
                "expected_user_id": recovery.expected_user_id,
                "expected_referral_id": recovery.expected_referral_id,
                "expected_reward_amount": recovery.expected_reward_amount,
                "expected_created_at": (
                    recovery.expected_created_at.isoformat()
                    if recovery.expected_created_at is not None
                    else None
                ),
                "expected_participant_merge_audit_ids": list(
                    recovery.expected_participant_merge_audit_ids
                ),
                "operator_reference": recovery.operator_reference,
                "reason": recovery.reason,
                "evidence_sha256": recovery.evidence_sha256,
            }
        else:
            request_entry = {
                "reward_id": recovery.reward_id,
                "action": recovery.action.value,
                "expected_version": recovery.expected_version,
                "source_transaction_id": recovery.source_transaction_id,
                "origin_referral_id": recovery.origin_referral_id,
                "level": recovery.level.value if recovery.level is not None else None,
                "expected_reward_amount": recovery.expected_reward_amount,
                "accrual_strategy_snapshot": (
                    recovery.accrual_strategy_snapshot.value
                    if recovery.accrual_strategy_snapshot is not None
                    else None
                ),
                "reward_strategy": (
                    recovery.reward_strategy.value
                    if recovery.reward_strategy is not None
                    else None
                ),
                "config_value": recovery.config_value,
                "operator_reference": recovery.operator_reference,
                "reason": recovery.reason,
                "evidence_sha256": recovery.evidence_sha256,
            }
        if not any(entry.model_dump() == request_entry for entry in manifest.entries):
            raise LegacyReferralRecoveryAuthorizationError(
                "Legacy recovery request is not an exact trusted manifest entry"
            )
        digest = self.config.referral_reward_legacy_recovery_manifest_sha256
        if digest is None:
            raise LegacyReferralRecoveryAuthorizationError(
                "Trusted recovery manifest digest disappeared"
            )
        return digest

    def _load_manifest(self) -> _RecoveryManifest:  # noqa: C901
        if self._manifest is not None:
            return self._manifest
        if not self.config.referral_reward_legacy_recovery_enabled:
            raise LegacyReferralRecoveryAuthorizationError(
                "Legacy referral recovery gate is disabled"
            )
        path = self.config.referral_reward_legacy_recovery_manifest_path
        expected_digest = self.config.referral_reward_legacy_recovery_manifest_sha256
        if path is None or expected_digest is None or not Path(path).is_absolute():
            raise LegacyReferralRecoveryAuthorizationError(
                "Trusted recovery manifest configuration is incomplete"
            )
        try:
            payload = Path(path).read_bytes()
        except OSError as exc:
            raise LegacyReferralRecoveryAuthorizationError(
                "Trusted recovery manifest cannot be read"
            ) from exc
        if len(payload) > MAX_MANIFEST_BYTES:
            raise LegacyReferralRecoveryAuthorizationError(
                "Trusted recovery manifest exceeds the size limit"
            )
        try:
            parsed = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LegacyReferralRecoveryAuthorizationError(
                "Trusted recovery manifest is not canonical JSON"
            ) from exc
        actual_digest = canonical_legacy_recovery_manifest_sha256(parsed)
        if not secrets.compare_digest(actual_digest, expected_digest):
            raise LegacyReferralRecoveryAuthorizationError(
                "Trusted recovery manifest SHA-256 does not match configuration"
            )
        try:
            if not isinstance(parsed, dict):
                raise ValueError("Manifest root must be an object")
            if parsed.get("version") == 1:
                manifest: _RecoveryManifest = _RecoveryManifestV1.model_validate(parsed)
            elif parsed.get("version") == 2:
                manifest = _RecoveryManifestV2.model_validate(parsed)
            else:
                raise ValueError("Unsupported recovery manifest version")
        except ValueError as exc:
            raise LegacyReferralRecoveryAuthorizationError(
                "Trusted recovery manifest failed strict validation"
            ) from exc
        self._manifest = manifest
        return manifest

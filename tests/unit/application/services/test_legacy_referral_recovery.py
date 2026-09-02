import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.application.dto import LegacyReferralRewardRecoveryDto
from src.application.legacy_referral_recovery import (
    LegacyReferralRecoveryAuthorizationError,
    LegacyReferralRecoveryAuthorizer,
    canonical_legacy_recovery_manifest_sha256,
)
from src.core.constants import PROVIDER_SUCCEEDED_REFERRAL_EVIDENCE_SHA256
from src.core.enums import (
    LegacyReferralRewardRecoveryAction,
    LegacyReferralRewardSourceValidation,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardStrategy,
)


def _retry() -> LegacyReferralRewardRecoveryDto:
    return LegacyReferralRewardRecoveryDto(
        reward_id=1478,
        action=LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING,
        expected_version=1,
        source_transaction_id=8889,
        origin_referral_id=1678,
        level=ReferralLevel.FIRST,
        expected_reward_amount=14,
        accrual_strategy_snapshot=ReferralAccrualStrategy.ON_FIRST_PAYMENT,
        reward_strategy=ReferralRewardStrategy.AMOUNT,
        config_value=14,
        operator_reference="OWNER/INCIDENT-2026-08-22",
        reason="Canonical evidence",
        evidence_sha256="a" * 64,
    )


def _entry(recovery: LegacyReferralRewardRecoveryDto) -> dict[str, object]:
    return {
        "reward_id": recovery.reward_id,
        "action": recovery.action.value,
        "expected_version": recovery.expected_version,
        "source_transaction_id": recovery.source_transaction_id,
        "origin_referral_id": recovery.origin_referral_id,
        "level": recovery.level.value,
        "expected_reward_amount": recovery.expected_reward_amount,
        "accrual_strategy_snapshot": (
            recovery.accrual_strategy_snapshot.value
            if recovery.accrual_strategy_snapshot is not None
            else None
        ),
        "reward_strategy": (
            recovery.reward_strategy.value if recovery.reward_strategy is not None else None
        ),
        "config_value": recovery.config_value,
        "operator_reference": recovery.operator_reference,
        "reason": recovery.reason,
        "evidence_sha256": recovery.evidence_sha256,
    }


def _operator_retry() -> LegacyReferralRewardRecoveryDto:
    return LegacyReferralRewardRecoveryDto(
        reward_id=1342,
        action=LegacyReferralRewardRecoveryAction.RETRY_OPERATOR_DIRECTED,
        expected_version=1,
        source_transaction_id=8123,
        origin_referral_id=1500,
        level=ReferralLevel.FIRST,
        expected_reward_amount=14,
        accrual_strategy_snapshot=None,
        reward_strategy=None,
        config_value=None,
        operator_reference="OWNER/INCIDENT-2026-08-22-FULL-AUDIT",
        reason="FIFO timeline audit found no ADMIN day allocation after this reward",
        evidence_sha256="e" * 64,
        expected_user_id=222,
        expected_referral_id=1500,
        expected_created_at=datetime(2026, 7, 20, 12, 34, 56, 123456, tzinfo=timezone.utc),
        source_validation=LegacyReferralRewardSourceValidation.LOCAL_COMPLETED,
    )


def _operator_manifest(recovery: LegacyReferralRewardRecoveryDto) -> dict[str, object]:
    assert recovery.level is not None
    assert recovery.expected_created_at is not None
    return {
        "version": 2,
        "incident": "legacy-referral-rewards-2026-08-22-full-audit",
        "entry_count": 1,
        "entries": [
            {
                "reward_id": recovery.reward_id,
                "action": recovery.action.value,
                "expected_version": recovery.expected_version,
                "source_transaction_id": recovery.source_transaction_id,
                "origin_referral_id": recovery.origin_referral_id,
                "level": recovery.level.value,
                "source_validation": recovery.source_validation.value,
                "expected_user_id": recovery.expected_user_id,
                "expected_referral_id": recovery.expected_referral_id,
                "expected_reward_amount": recovery.expected_reward_amount,
                "expected_created_at": recovery.expected_created_at.isoformat(),
                "expected_participant_merge_audit_ids": list(
                    recovery.expected_participant_merge_audit_ids
                ),
                "operator_reference": recovery.operator_reference,
                "reason": recovery.reason,
                "evidence_sha256": recovery.evidence_sha256,
            }
        ],
        "audit_evidence_sha256": (
            recovery.evidence_sha256
            if recovery.source_validation
            == LegacyReferralRewardSourceValidation.LOCAL_COMPLETED
            else "f" * 64
        ),
        "allocation_rule": "ADMIN_DAYS_FIFO_AFTER_REWARD",
    }


def _manifest(recovery: LegacyReferralRewardRecoveryDto) -> dict[str, object]:
    second_retry = replace(
        _retry(),
        reward_id=1486,
        source_transaction_id=8978,
        origin_referral_id=1618,
        level=ReferralLevel.SECOND,
        expected_reward_amount=7,
        config_value=7,
        evidence_sha256="b" * 64,
    )
    admin_entries = [
        replace(
            _retry(),
            reward_id=reward_id,
            action=LegacyReferralRewardRecoveryAction.CONFIRM_ADMIN_COMPENSATED,
            source_transaction_id=source_id,
            origin_referral_id=origin_id,
            expected_reward_amount=14,
            accrual_strategy_snapshot=None,
            reward_strategy=None,
            config_value=None,
            evidence_sha256="c" * 64,
        )
        for reward_id, source_id, origin_id in (
            (398, 3987, 788),
            (399, 3988, 956),
            (507, 4505, 1025),
            (637, 5224, 956),
            (638, 5225, 1025),
            (897, 6235, 1347),
            (932, 6365, 1366),
        )
    ]
    entries = [_retry(), second_retry, *admin_entries]
    replacement_index = (
        0 if recovery.action == LegacyReferralRewardRecoveryAction.RETRY_PROVEN_MISSING else 2
    )
    entries[replacement_index] = recovery
    return {
        "version": 1,
        "incident": "legacy-referral-rewards-2026-08-22",
        "entry_count": 9,
        "entries": [_entry(entry) for entry in entries],
        "admin_compensation": {
            "total_granted_days": 107,
            "allocated_days": 98,
            "unallocated_days": 9,
            "coverage_evidence_sha256": "c" * 64,
        },
    }


def _authorizer(path: Path, manifest: dict[str, object]) -> LegacyReferralRecoveryAuthorizer:
    path.write_text(json.dumps(manifest), encoding="utf-8")
    config = SimpleNamespace(
        referral_reward_legacy_recovery_enabled=True,
        referral_reward_legacy_recovery_manifest_path=path,
        referral_reward_legacy_recovery_manifest_sha256=(
            canonical_legacy_recovery_manifest_sha256(manifest)
        ),
    )
    return LegacyReferralRecoveryAuthorizer(config)  # type: ignore[arg-type]


def test_manifest_gate_authorizes_only_exact_finite_entry(tmp_path: Path) -> None:
    recovery = _retry()
    authorizer = _authorizer(tmp_path / "manifest.json", _manifest(recovery))

    assert authorizer.authorize(recovery) == canonical_legacy_recovery_manifest_sha256(
        _manifest(recovery)
    )
    for changed in (
        replace(recovery, reward_id=1479),
        replace(recovery, source_transaction_id=8890),
        replace(recovery, expected_reward_amount=15),
        replace(recovery, operator_reference="OWNER/DIFFERENT-INCIDENT"),
        replace(recovery, reason="Different decision"),
        replace(recovery, evidence_sha256="b" * 64),
    ):
        with pytest.raises(
            LegacyReferralRecoveryAuthorizationError,
            match="not an exact trusted manifest entry",
        ):
            authorizer.authorize(changed)

    with pytest.raises(
        LegacyReferralRecoveryAuthorizationError,
        match="fixed to ADMIN_API",
    ):
        authorizer.authorize(replace(recovery, resolved_by="SYSTEM"))


def test_manifest_gate_is_disabled_by_default() -> None:
    config = SimpleNamespace(
        referral_reward_legacy_recovery_enabled=False,
        referral_reward_legacy_recovery_manifest_path=None,
        referral_reward_legacy_recovery_manifest_sha256=None,
    )
    authorizer = LegacyReferralRecoveryAuthorizer(config)  # type: ignore[arg-type]

    with pytest.raises(LegacyReferralRecoveryAuthorizationError, match="gate is disabled"):
        authorizer.authorize(_retry())


def test_v2_manifest_authorizes_only_exact_operator_directed_row(tmp_path: Path) -> None:
    recovery = _operator_retry()
    manifest = _operator_manifest(recovery)
    authorizer = _authorizer(tmp_path / "manifest-v2.json", manifest)

    assert authorizer.authorize(recovery) == canonical_legacy_recovery_manifest_sha256(manifest)
    for changed in (
        replace(recovery, source_transaction_id=8124),
        replace(recovery, expected_user_id=223),
        replace(recovery, expected_referral_id=1501),
        replace(recovery, expected_reward_amount=7),
        replace(recovery, expected_participant_merge_audit_ids=(3,)),
        replace(
            recovery,
            expected_created_at=datetime(2026, 7, 20, 12, 34, 57, tzinfo=timezone.utc),
        ),
    ):
        with pytest.raises(
            LegacyReferralRecoveryAuthorizationError,
            match="not an exact trusted manifest entry",
        ):
            authorizer.authorize(changed)


def test_v2_manifest_rejects_duplicate_reward_ids(tmp_path: Path) -> None:
    recovery = _operator_retry()
    manifest = _operator_manifest(recovery)
    manifest["entry_count"] = 2
    manifest["entries"] = [*manifest["entries"], *manifest["entries"]]  # type: ignore[misc]

    with pytest.raises(
        LegacyReferralRecoveryAuthorizationError,
        match="failed strict validation",
    ):
        _authorizer(tmp_path / "manifest-v2.json", manifest)


def test_v2_provider_source_class_requires_pinned_evidence(tmp_path: Path) -> None:
    recovery = replace(
        _operator_retry(),
        reward_id=65,
        source_transaction_id=1761,
        source_validation=LegacyReferralRewardSourceValidation.PROVIDER_SUCCEEDED,
        evidence_sha256=PROVIDER_SUCCEEDED_REFERRAL_EVIDENCE_SHA256,
    )
    manifest = _operator_manifest(recovery)
    authorizer = _authorizer(tmp_path / "provider-manifest.json", manifest)
    assert authorizer.authorize(recovery) == canonical_legacy_recovery_manifest_sha256(manifest)

    bad_manifest = _operator_manifest(replace(recovery, evidence_sha256="0" * 64))
    with pytest.raises(
        LegacyReferralRecoveryAuthorizationError,
        match="failed strict validation",
    ):
        _authorizer(tmp_path / "bad-provider-manifest.json", bad_manifest)


def test_manifest_gate_enforces_admin_allocation_conservation(tmp_path: Path) -> None:
    recovery = replace(
        _retry(),
        reward_id=398,
        action=LegacyReferralRewardRecoveryAction.CONFIRM_ADMIN_COMPENSATED,
        source_transaction_id=3987,
        origin_referral_id=788,
        expected_reward_amount=14,
        accrual_strategy_snapshot=None,
        reward_strategy=None,
        config_value=None,
        evidence_sha256="c" * 64,
    )
    manifest = _manifest(recovery)
    manifest["admin_compensation"] = {
        "total_granted_days": 107,
        "allocated_days": 13,
        "unallocated_days": 94,
    }
    with pytest.raises(
        LegacyReferralRecoveryAuthorizationError,
        match="failed strict validation",
    ):
        _authorizer(tmp_path / "manifest.json", manifest)


def test_manifest_gate_rejects_digest_drift(tmp_path: Path) -> None:
    recovery = _retry()
    manifest = _manifest(recovery)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    config = SimpleNamespace(
        referral_reward_legacy_recovery_enabled=True,
        referral_reward_legacy_recovery_manifest_path=path,
        referral_reward_legacy_recovery_manifest_sha256="f" * 64,
    )

    with pytest.raises(LegacyReferralRecoveryAuthorizationError, match="does not match"):
        LegacyReferralRecoveryAuthorizer(config)  # type: ignore[arg-type]


def test_tracked_incident_manifest_is_exact_and_reproducible() -> None:
    path = (
        Path(__file__).parents[4]
        / "src"
        / "infrastructure"
        / "recovery_manifests"
        / "legacy_referral_rewards_2026-08-22.v1.json"
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert canonical_legacy_recovery_manifest_sha256(manifest) == (
        "51284b6c833968bf4e855de30fabe4616a616ab320d000fba399c6f280cf3506"
    )
    assert manifest["entry_count"] == len(manifest["entries"]) == 9
    assert {entry["reward_id"] for entry in manifest["entries"]} == {
        1478,
        1486,
        398,
        399,
        507,
        637,
        638,
        897,
        932,
    }
    admin_entries = [
        entry for entry in manifest["entries"] if entry["action"] == "CONFIRM_ADMIN_COMPENSATED"
    ]
    assert sum(entry["expected_reward_amount"] for entry in admin_entries) == 98
    assert manifest["admin_compensation"] == {
        "total_granted_days": 107,
        "allocated_days": 98,
        "unallocated_days": 9,
        "coverage_evidence_sha256": (
            "fb3dd384f6b42c2885056d9647f4842054052ea8fae349ae88810afd8e8995a1"
        ),
    }

    config = SimpleNamespace(
        referral_reward_legacy_recovery_enabled=True,
        referral_reward_legacy_recovery_manifest_path=path.resolve(),
        referral_reward_legacy_recovery_manifest_sha256=(
            "51284b6c833968bf4e855de30fabe4616a616ab320d000fba399c6f280cf3506"
        ),
    )
    authorizer = LegacyReferralRecoveryAuthorizer(config)  # type: ignore[arg-type]
    for entry in manifest["entries"]:
        recovery = LegacyReferralRewardRecoveryDto(
            reward_id=entry["reward_id"],
            action=LegacyReferralRewardRecoveryAction(entry["action"]),
            expected_version=entry["expected_version"],
            source_transaction_id=entry["source_transaction_id"],
            origin_referral_id=entry["origin_referral_id"],
            level=ReferralLevel(entry["level"]),
            expected_reward_amount=entry["expected_reward_amount"],
            accrual_strategy_snapshot=(
                ReferralAccrualStrategy(entry["accrual_strategy_snapshot"])
                if entry["accrual_strategy_snapshot"] is not None
                else None
            ),
            reward_strategy=(
                ReferralRewardStrategy(entry["reward_strategy"])
                if entry["reward_strategy"] is not None
                else None
            ),
            config_value=entry["config_value"],
            operator_reference=entry["operator_reference"],
            reason=entry["reason"],
            evidence_sha256=entry["evidence_sha256"],
        )
        assert authorizer.authorize(recovery) == (
            "51284b6c833968bf4e855de30fabe4616a616ab320d000fba399c6f280cf3506"
        )


def test_tracked_v2_operator_manifest_and_audit_are_exact_and_reproducible() -> None:
    manifests = Path(__file__).parents[4] / "src" / "infrastructure" / "recovery_manifests"
    manifest_path = manifests / "legacy_referral_rewards_2026-08-22.v2.json"
    audit_path = manifests / "legacy_referral_rewards_2026-08-22.v2.audit.json"
    provider_path = manifests / "legacy_referral_rewards_2026-08-22.v2.provider-rr65.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    provider_evidence = json.loads(provider_path.read_text(encoding="utf-8"))

    assert canonical_legacy_recovery_manifest_sha256(manifest) == (
        "85bd8c980abc52f6457c015f17ae635f86e3f5c42e8dc1105f6dfc82292fb23c"
    )
    assert canonical_legacy_recovery_manifest_sha256(audit) == (
        "dfac82651078009491e19be3d01f0af2a7c6e709b82f414a28754951c20b8beb"
    )
    assert canonical_legacy_recovery_manifest_sha256(provider_evidence) == (
        PROVIDER_SUCCEEDED_REFERRAL_EVIDENCE_SHA256
    )
    assert manifest["audit_evidence_sha256"] == (
        "dfac82651078009491e19be3d01f0af2a7c6e709b82f414a28754951c20b8beb"
    )
    assert manifest["entry_count"] == len(manifest["entries"]) == 759
    assert sum(entry["expected_reward_amount"] for entry in manifest["entries"]) == 9408
    assert manifest["entries"][0]["reward_id"] == 65
    assert manifest["entries"][0]["source_transaction_id"] == 1761
    assert manifest["entries"][0]["source_validation"] == "PROVIDER_SUCCEEDED"
    assert manifest["entries"][0]["evidence_sha256"] == (
        PROVIDER_SUCCEEDED_REFERRAL_EVIDENCE_SHA256
    )
    assert sum(
        entry["source_validation"] == "PROVIDER_SUCCEEDED"
        for entry in manifest["entries"]
    ) == 1
    assert all(
        entry["evidence_sha256"] == manifest["audit_evidence_sha256"]
        for entry in manifest["entries"]
        if entry["source_validation"] == "LOCAL_COMPLETED"
    )
    direct_merge_mapping = {
        str(entry["reward_id"]): entry["expected_participant_merge_audit_ids"]
        for entry in manifest["entries"]
        if entry.get("expected_participant_merge_audit_ids")
    }
    assert len(direct_merge_mapping) == 70
    assert sum(len(audit_ids) for audit_ids in direct_merge_mapping.values()) == 71
    assert canonical_legacy_recovery_manifest_sha256(direct_merge_mapping) == (
        "5e77ef5c3cd03a23b236886d30743bd59f360cfd8457857108676bad1ab74060"
    )
    assert audit["schema_version"] == 2
    assert audit["user_merge_lineage_audit"]["canonical_inbound_rewards"] == 70
    assert audit["user_merge_lineage_audit"]["outbound_rewards"] == 0
    assert audit["user_merge_lineage_audit"]["invalid_rewards"] == 0
    assert audit["user_merge_lineage_audit"]["direct_reward_audit_mapping_sha256"] == (
        "5e77ef5c3cd03a23b236886d30743bd59f360cfd8457857108676bad1ab74060"
    )
    assert audit["admin_duration_audit"][
        "retained_positive_events_to_merged_recipient_aliases"
    ] == 0
    source_levels = {
        (entry["source_transaction_id"], entry["level"])
        for entry in manifest["entries"]
    }
    assert len(source_levels) == len(manifest["entries"])

    config = SimpleNamespace(
        referral_reward_legacy_recovery_enabled=True,
        referral_reward_legacy_recovery_manifest_path=manifest_path.resolve(),
        referral_reward_legacy_recovery_manifest_sha256=(
            "85bd8c980abc52f6457c015f17ae635f86e3f5c42e8dc1105f6dfc82292fb23c"
        ),
    )
    authorizer = LegacyReferralRecoveryAuthorizer(config)  # type: ignore[arg-type]
    for entry in (manifest["entries"][0], manifest["entries"][-1]):
        recovery = LegacyReferralRewardRecoveryDto(
            reward_id=entry["reward_id"],
            action=LegacyReferralRewardRecoveryAction(entry["action"]),
            expected_version=entry["expected_version"],
            source_transaction_id=entry["source_transaction_id"],
            origin_referral_id=entry["origin_referral_id"],
            level=ReferralLevel(entry["level"]),
            expected_reward_amount=entry["expected_reward_amount"],
            accrual_strategy_snapshot=None,
            reward_strategy=None,
            config_value=None,
            operator_reference=entry["operator_reference"],
            reason=entry["reason"],
            evidence_sha256=entry["evidence_sha256"],
            expected_user_id=entry["expected_user_id"],
            expected_referral_id=entry["expected_referral_id"],
            expected_created_at=datetime.fromisoformat(entry["expected_created_at"]),
            expected_participant_merge_audit_ids=tuple(
                entry.get("expected_participant_merge_audit_ids", [])
            ),
            source_validation=LegacyReferralRewardSourceValidation(
                entry["source_validation"]
            ),
        )
        assert authorizer.authorize(recovery) == (
            "85bd8c980abc52f6457c015f17ae635f86e3f5c42e8dc1105f6dfc82292fb23c"
        )

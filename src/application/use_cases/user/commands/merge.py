from dataclasses import dataclass

from src.application.common import Interactor
from src.application.common.dao import (
    UserMergeDao,
    UserMergeNotFoundError,
    UserMergePaymentOperationConflictError,
    UserMergePlan,
    UserMergeReferralAttributionConflictError,
    UserMergeTargetConflictError,
)
from src.application.common.dao.user_merge import (
    EmailConflictResolution,
    PaymentConflictResolution,
    TelegramConflictResolution,
    UserMergeTargetSnapshot,
)
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto


class MergeUsersError(Exception):
    status_code = 400


class MergeUsersNotFoundError(MergeUsersError):
    status_code = 404


class MergeUsersConflictError(MergeUsersError):
    status_code = 409


@dataclass(frozen=True)
class MergeUsersDto:
    source_user_id: int
    target_user_id: int
    reason: str
    dry_run: bool = False
    email_resolution: EmailConflictResolution = EmailConflictResolution.REJECT
    telegram_resolution: TelegramConflictResolution = TelegramConflictResolution.REJECT
    payment_resolution: PaymentConflictResolution = PaymentConflictResolution.REJECT


@dataclass(frozen=True)
class MergeUsersResultDto:
    dry_run: bool
    source_user_id: int
    target_user_id: int
    target: UserMergeTargetSnapshot
    moved: dict[str, int]
    conflicts: list[str]
    requires_relogin: bool = True


class MergeUsers(Interactor[MergeUsersDto, MergeUsersResultDto]):
    required_permission = Permission.USER_MERGE

    def __init__(self, uow: UnitOfWork, user_merge_dao: UserMergeDao) -> None:
        self.uow = uow
        self.user_merge_dao = user_merge_dao

    async def _execute(self, actor: UserDto, data: MergeUsersDto) -> MergeUsersResultDto:
        reason = data.reason.strip()
        if not reason:
            raise MergeUsersConflictError("Merge reason is required")
        if data.source_user_id == data.target_user_id:
            raise MergeUsersConflictError("Source and target users must be different")

        async with self.uow:
            try:
                plan = await self.user_merge_dao.plan(
                    data.source_user_id,
                    data.target_user_id,
                    email_resolution=data.email_resolution,
                    telegram_resolution=data.telegram_resolution,
                    payment_resolution=data.payment_resolution,
                )
            except UserMergeNotFoundError as exc:
                raise MergeUsersNotFoundError(str(exc)) from exc
            except UserMergeTargetConflictError as exc:
                raise MergeUsersConflictError(str(exc)) from exc

            if data.dry_run:
                await self.uow.rollback()
                return self._result(data, plan)

            if plan.conflicts:
                raise MergeUsersConflictError("; ".join(plan.conflicts))

            try:
                merged = await self.user_merge_dao.merge(
                    actor=actor,
                    source_user_id=data.source_user_id,
                    target_user_id=data.target_user_id,
                    reason=reason,
                    email_resolution=data.email_resolution,
                    telegram_resolution=data.telegram_resolution,
                    payment_resolution=data.payment_resolution,
                )
            except UserMergePaymentOperationConflictError as exc:
                raise MergeUsersConflictError(str(exc)) from exc
            except UserMergeReferralAttributionConflictError as exc:
                raise MergeUsersConflictError(str(exc)) from exc
            except UserMergeTargetConflictError as exc:
                raise MergeUsersConflictError(str(exc)) from exc
            await self.uow.commit()
            return self._result(data, merged)

    def _result(self, data: MergeUsersDto, plan: UserMergePlan) -> MergeUsersResultDto:
        return MergeUsersResultDto(
            dry_run=data.dry_run,
            source_user_id=plan.source_user_id,
            target_user_id=plan.target_user_id,
            target=plan.target,
            moved=plan.moved,
            conflicts=plan.conflicts,
        )

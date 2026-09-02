from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, Security

from src.application.common.dao.user_merge import (
    EmailConflictResolution,
    PaymentConflictResolution,
    TelegramConflictResolution,
)
from src.application.use_cases.user.commands.merge import (
    MergeUsers,
    MergeUsersConflictError,
    MergeUsersDto,
    MergeUsersError,
    MergeUsersNotFoundError,
)
from src.web.dependencies import require_api_key
from src.web.schemas import MergeUsersRequest, MergeUsersResponse, MergeUsersTargetResponse

router = APIRouter(prefix="/users", tags=["Admin - Users"])


@router.post("/merge", response_model=MergeUsersResponse)
@inject
async def merge_users(
    body: MergeUsersRequest,
    merge_users_uc: FromDishka[MergeUsers],
    dry_run: bool = True,
    _: None = Security(require_api_key),
) -> MergeUsersResponse:
    try:
        result = await merge_users_uc.system(
            MergeUsersDto(
                source_user_id=body.source_user_id,
                target_user_id=body.target_user_id,
                reason=body.reason,
                dry_run=dry_run,
                email_resolution=EmailConflictResolution(body.email_resolution),
                telegram_resolution=TelegramConflictResolution(body.telegram_resolution),
                payment_resolution=PaymentConflictResolution(body.payment_resolution),
            )
        )
    except (MergeUsersConflictError, MergeUsersNotFoundError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except MergeUsersError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return MergeUsersResponse(
        dry_run=result.dry_run,
        source_user_id=result.source_user_id,
        target_user_id=result.target_user_id,
        target=MergeUsersTargetResponse(
            id=result.target.id,
            email=result.target.email,
            telegram_id=result.target.telegram_id,
            is_email_verified=result.target.is_email_verified,
            current_subscription_id=result.target.current_subscription_id,
        ),
        moved=result.moved,
        conflicts=result.conflicts,
        requires_relogin=result.requires_relogin,
    )

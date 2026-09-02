from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.infrastructure.database.models import Referral

# ASCII "REFERRAL" encoded as a positive signed bigint. Referral attachment,
# account merge, and the database referral-edge trigger all use this
# transaction-scoped lock so graph validation and mutation are serialized.
REFERRAL_GRAPH_ADVISORY_LOCK_ID = 0x524546455252414C


async def acquire_referral_graph_lock(session: AsyncSession) -> None:
    await session.execute(select(func.pg_advisory_xact_lock(REFERRAL_GRAPH_ADVISORY_LOCK_ID)))


def referral_path_statement(
    ancestor_user_id: int,
    descendant_user_id: int,
) -> Select[Any]:
    """Return a cycle-safe query counting paths between two referral users."""
    descendants = (
        select(Referral.referred_id.label("user_id"))
        .where(Referral.referrer_id == ancestor_user_id)
        .cte("referral_descendants", recursive=True)
    )
    next_referral = Referral.__table__.alias("next_referral")
    descendants = descendants.union(
        select(next_referral.c.referred_id).join(
            descendants,
            next_referral.c.referrer_id == descendants.c.user_id,
        )
    )
    return (
        select(func.count())
        .select_from(descendants)
        .where(descendants.c.user_id == descendant_user_id)
    )

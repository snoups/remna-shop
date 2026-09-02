from dataclasses import dataclass
from typing import Optional

from loguru import logger

from src.application.common import EventPublisher, Interactor
from src.application.common.dao import ReferralDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import ReferralDto, UserDto
from src.application.events import ReferralAttachedEvent
from src.core.enums import ReferralLevel


@dataclass(frozen=True)
class AttachReferralDto:
    user_id: int
    referral_code: str


class AttachReferral(Interactor[AttachReferralDto, Optional[UserDto]]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        referral_dao: ReferralDao,
        event_publisher: EventPublisher,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.referral_dao = referral_dao
        self.event_publisher = event_publisher

    async def _execute(self, actor: UserDto, data: AttachReferralDto) -> Optional[UserDto]:
        # Attach the referrer relationship regardless of whether the referral rewards
        # program is enabled: the relationship is needed for invite-only access display
        # and statistics. Reward accrual is gated separately in AssignReferralRewards.
        async with self.uow:
            # Account merge takes the same graph lock before changing canonical
            # ownership. Resolve the code only after this lock so an old source
            # code cannot race into a newly merged, inactive account.
            await self.referral_dao.lock_referral_graph()
            referrer = await self.user_dao.get_by_referral_code(data.referral_code)

            if not referrer:
                logger.info(
                    f"Referral skipped: referrer not found for code '{data.referral_code}'"
                )
                await self.uow.commit()
                return None

            if referrer.id == data.user_id:
                logger.warning(
                    f"Referral skipped: self-referral by user '{data.user_id}' "
                    f"with code '{data.referral_code}'"
                )
                await self.uow.commit()
                return None

            # Serialize attachment with first-payment intent creation and account
            # merge. The existing-check must happen only after this shared fence.
            await self.referral_dao.lock_referral_attribution(
                data.user_id,
                (referrer.id,),
            )
            existing, _ = await self.referral_dao.get_referral_chain(data.user_id)
            if existing:
                logger.info(f"Referral skipped: user '{data.user_id}' already referred")
                await self.uow.commit()
                return None

            # Adding referrer -> referred is invalid when the referred user is
            # already an ancestor of the referrer. The database repeats this
            # check as the final concurrency-safe invariant.
            if await self.referral_dao.has_referral_path(data.user_id, referrer.id):
                logger.warning(
                    f"Referral skipped: edge '{referrer.id}' -> '{data.user_id}' "
                    "would create a cycle"
                )
                await self.uow.commit()
                return None

            referred = await self.user_dao.get_by_id(data.user_id)
            if not referred:
                logger.warning(f"Referral skipped: referred user not found '{data.user_id}'")
                await self.uow.commit()
                return None

            logger.info(
                f"Referral detected '{referrer.remna_name}' -> "
                f"'{data.user_id}'"
            )

            await self.referral_dao.create_referral(
                ReferralDto(
                    # A stored referral is always the direct attribution edge.
                    # L2 is relative to the viewer/reward recipient and must be
                    # derived by traversing the chain, not persisted on this edge.
                    level=ReferralLevel.FIRST,
                    referrer=referrer,
                    referred=referred,
                )
            )
            await self.uow.commit()

        await self.event_publisher.publish(ReferralAttachedEvent(user=referrer, name=referred.name))

        return referrer

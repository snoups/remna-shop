from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import SettingsDao, TransactionDao
from src.application.dto import UserDto


class IsStarsPaymentBlocked(Interactor[UserDto, bool]):
    required_permission = None

    def __init__(self, settings_dao: SettingsDao, transaction_dao: TransactionDao) -> None:
        self.settings_dao = settings_dao
        self.transaction_dao = transaction_dao

    async def _execute(self, actor: UserDto, data: UserDto) -> bool:
        settings = await self.settings_dao.get()

        if not settings.extra.stars_require_paid_purchase:
            return False

        has_paid = await self.transaction_dao.has_paid_purchase_excluding_stars(data.id)
        blocked = not has_paid

        if blocked:
            logger.info(f"{data.log} Stars payment blocked: no prior non-stars paid purchase")
        return blocked

from fastapi import APIRouter

from src.core.constants import API_V1

from .payment_operations import router as payment_operations_router
from .referral_rewards import router as referral_rewards_router
from .users import router as users_router

router = APIRouter(prefix=API_V1 + "/admin")
router.include_router(users_router)
router.include_router(payment_operations_router)
router.include_router(referral_rewards_router)

__all__ = ["router"]

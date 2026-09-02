from dataclasses import dataclass

from src.application.common import Interactor
from src.application.common.dao import ReferralDao, SubscriptionDao, TransactionDao, UserDao
from src.application.common.policy import Permission
from src.application.dto import UserDto, UserStatisticsDto
from src.core.utils.converters import percent


@dataclass(frozen=True)
class UsersStatisticsDto:
    total_users: int
    new_users_daily: int
    new_users_weekly: int
    new_users_monthly: int
    users_with_subscription: int
    users_without_subscription: int
    users_with_trial: int
    blocked_users: int
    bot_blocked_users: int
    user_conversion: float
    trial_conversion: float


class GetUsersStatistics(Interactor[None, UsersStatisticsDto]):
    required_permission = Permission.VIEW_STATISTICS

    def __init__(
        self,
        user_dao: UserDao,
        transaction_dao: TransactionDao,
        subscription_dao: SubscriptionDao,
    ) -> None:
        self.user_dao = user_dao
        self.transaction_dao = transaction_dao
        self.subscription_dao = subscription_dao

    async def _execute(self, actor: UserDto, data: None) -> UsersStatisticsDto:
        total_users = await self.user_dao.count()
        blocked_users = await self.user_dao.count_blocked()
        bot_blocked_users = await self.user_dao.count_bot_blocked()
        users_with_sub = await self.user_dao.count_with_active_subscription()
        users_without_sub = await self.user_dao.count_without_subscription()
        users_with_trial = await self.user_dao.count_with_trial_subscription()
        new_daily = await self.user_dao.count_new(days=0)
        new_weekly = await self.user_dao.count_new(days=7)
        new_monthly = await self.user_dao.count_new(days=30)
        paying_users = await self.transaction_dao.count_paying_users()
        total_trials = await self.subscription_dao.count_total_trials()
        converted_from_trial = await self.subscription_dao.count_converted_from_trial()

        return UsersStatisticsDto(
            total_users=total_users,
            new_users_daily=new_daily,
            new_users_weekly=new_weekly,
            new_users_monthly=new_monthly,
            users_with_subscription=users_with_sub,
            users_without_subscription=users_without_sub,
            users_with_trial=users_with_trial,
            blocked_users=blocked_users,
            bot_blocked_users=bot_blocked_users,
            user_conversion=percent(paying_users, total_users),
            trial_conversion=percent(converted_from_trial, total_trials),
        )


class GetUserStatistics(Interactor[int, UserStatisticsDto]):
    required_permission = Permission.USER_EDITOR

    def __init__(
        self,
        user_dao: UserDao,
        transaction_dao: TransactionDao,
        referral_dao: ReferralDao,
    ) -> None:
        self.user_dao = user_dao
        self.transaction_dao = transaction_dao
        self.referral_dao = referral_dao

    async def _execute(self, actor: UserDto, user_id: int) -> UserStatisticsDto:
        user = await self.user_dao.get_by_id(user_id)
        if not user:
            raise ValueError(f"User '{user_id}' not found")

        if user.created_at is None:
            raise RuntimeError("A persisted user must have a creation timestamp")
        last_payment_at, payment_amounts = await self.transaction_dao.get_user_payment_stats(
            user.id
        )
        referral_stats = await self.referral_dao.get_user_referral_stats(user.id)

        return UserStatisticsDto(
            last_payment_at=last_payment_at,
            payment_amounts=payment_amounts,
            registered_at=user.created_at,
            referrer_telegram_id=referral_stats.referrer_telegram_id,
            referrer_email=referral_stats.referrer_email,
            referrer_username=referral_stats.referrer_username,
            referrals_level_1=referral_stats.referrals_level_1,
            referrals_level_2=referral_stats.referrals_level_2,
            reward_points=referral_stats.reward_points,
            reward_days=referral_stats.reward_days,
        )

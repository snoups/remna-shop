from dishka import Provider, Scope, provide

from src.application.common.dao import (
    AdLinkDao,
    AuthSessionDao,
    BroadcastDao,
    PaymentGatewayDao,
    PaymentOperationDao,
    PlanDao,
    PromocodeDao,
    RecentActivityDao,
    ReferralDao,
    SettingsDao,
    SubscriptionDao,
    SubscriptionEmailReminderDao,
    TransactionDao,
    UserDao,
    UserMergeDao,
    UserOAuthProviderDao,
    WaitlistDao,
    WebhookDao,
)
from src.infrastructure.database.dao import (
    AdLinkDaoImpl,
    BroadcastDaoImpl,
    PaymentGatewayDaoImpl,
    PaymentOperationDaoImpl,
    PlanDaoImpl,
    PromocodeDaoImpl,
    ReferralDaoImpl,
    SettingsDaoImpl,
    SubscriptionDaoImpl,
    SubscriptionEmailReminderDaoImpl,
    TransactionDaoImpl,
    UserDaoImpl,
    UserMergeDaoImpl,
    UserOAuthProviderDaoImpl,
    WaitlistDaoImpl,
    WebhookDaoImpl,
)
from src.infrastructure.redis.activity import RedisActivityRepository
from src.infrastructure.redis.auth import RedisAuthRepository


class DaoProvider(Provider):
    scope = Scope.REQUEST

    ad_link = provide(source=AdLinkDaoImpl, provides=AdLinkDao)
    broadcast = provide(source=BroadcastDaoImpl, provides=BroadcastDao)
    payment_gateway = provide(source=PaymentGatewayDaoImpl, provides=PaymentGatewayDao)
    payment_operation = provide(source=PaymentOperationDaoImpl, provides=PaymentOperationDao)
    plan = provide(source=PlanDaoImpl, provides=PlanDao)
    promocode = provide(source=PromocodeDaoImpl, provides=PromocodeDao)
    referral = provide(source=ReferralDaoImpl, provides=ReferralDao)
    settings = provide(source=SettingsDaoImpl, provides=SettingsDao)
    subscription = provide(source=SubscriptionDaoImpl, provides=SubscriptionDao)
    subscription_email_reminder = provide(
        source=SubscriptionEmailReminderDaoImpl,
        provides=SubscriptionEmailReminderDao,
    )
    transaction = provide(source=TransactionDaoImpl, provides=TransactionDao)
    user = provide(source=UserDaoImpl, provides=UserDao)
    user_merge = provide(source=UserMergeDaoImpl, provides=UserMergeDao)
    oauth_provider = provide(source=UserOAuthProviderDaoImpl, provides=UserOAuthProviderDao)

    webhook = provide(source=WebhookDaoImpl, provides=WebhookDao, scope=Scope.APP)
    waitlist = provide(source=WaitlistDaoImpl, provides=WaitlistDao, scope=Scope.APP)
    auth_session = provide(source=RedisAuthRepository, provides=AuthSessionDao, scope=Scope.APP)
    recent_activity = provide(
        source=RedisActivityRepository, provides=RecentActivityDao, scope=Scope.APP
    )

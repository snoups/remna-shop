from dishka import AnyOf, Provider, Scope, alias, provide

from src.application.common import (
    BotService,
    BroadcastDispatcher,
    Cryptographer,
    EmailSender,
    EventPublisher,
    EventSubscriber,
    FileDownloader,
    HttpClient,
    Notifier,
    PasswordHasher,
    PaymentNotificationDispatcher,
    Redirect,
    Remnawave,
    SubscriptionMutationLock,
    XuiDbReader,
)
from src.application.legacy_referral_recovery import (
    LegacyReferralRecoveryAuthorizer,
)
from src.application.services import (
    PaymentCursorCodec,
    PaymentIdempotencyService,
    PaymentReconciliationService,
    PricingService,
    RemnaWebhookService,
)
from src.infrastructure.services import (
    AiogramFileDownloader,
    AiohttpClient,
    BotServiceImpl,
    BroadcastDispatcherImpl,
    CommandService,
    CryptographerImpl,
    EventBusImpl,
    HealthService,
    NotificationQueue,
    NotificationService,
    NotificationWorker,
    PasswordHasherImpl,
    PaymentNotificationDispatcherImpl,
    RedirectImpl,
    RedisSubscriptionMutationLock,
    RemnawaveImpl,
    SmtpEmailSender,
    WebhookService,
    XuiDbReaderImpl,
)


class ServicesProvider(Provider):
    scope = Scope.APP

    bot = provide(source=BotServiceImpl, provides=BotService)
    health = provide(source=HealthService)
    cryptographer = provide(source=CryptographerImpl, provides=Cryptographer)
    password_hasher = provide(source=PasswordHasherImpl, provides=PasswordHasher)
    email_sender = provide(source=SmtpEmailSender, provides=EmailSender)
    http_client = provide(source=AiohttpClient, provides=HttpClient)
    redirect = provide(source=RedirectImpl, provides=Redirect)
    pricing = provide(source=PricingService)
    payment_idempotency = provide(source=PaymentIdempotencyService, scope=Scope.REQUEST)
    payment_reconciliation = provide(source=PaymentReconciliationService, scope=Scope.REQUEST)
    payment_cursor = provide(source=PaymentCursorCodec)
    legacy_referral_recovery_authorizer = provide(
        source=LegacyReferralRecoveryAuthorizer,
    )
    event_bus = provide(EventBusImpl)
    publisher = alias(source=EventBusImpl, provides=EventPublisher)
    subscriber = alias(source=EventBusImpl, provides=EventSubscriber)
    file_downloader = provide(source=AiogramFileDownloader, provides=FileDownloader)

    command = provide(source=CommandService)
    webhook = provide(source=WebhookService)

    remnawave = provide(source=RemnawaveImpl, provides=Remnawave)
    subscription_mutation_lock = provide(
        source=RedisSubscriptionMutationLock,
        provides=SubscriptionMutationLock,
    )
    remna_webhook = provide(source=RemnaWebhookService, scope=Scope.REQUEST)

    notification_queue = provide(source=NotificationQueue)
    notification_worker = provide(source=NotificationWorker)
    notification = provide(
        NotificationService,
        scope=Scope.REQUEST,
        provides=AnyOf[Notifier, NotificationService],
    )

    payment_dispatcher = provide(
        source=PaymentNotificationDispatcherImpl,
        provides=PaymentNotificationDispatcher,
        scope=Scope.APP,
    )
    broadcast_dispatcher = provide(
        source=BroadcastDispatcherImpl,
        provides=BroadcastDispatcher,
        scope=Scope.APP,
    )
    xui_reader = provide(source=XuiDbReaderImpl, provides=XuiDbReader, scope=Scope.APP)

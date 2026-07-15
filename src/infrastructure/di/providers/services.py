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
    XuiDbReader,
)
from src.application.services import (
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
    OutboundWebhookSender,
    OutboundWebhookService,
    PasswordHasherImpl,
    PaymentNotificationDispatcherImpl,
    RedirectImpl,
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
    event_bus = provide(EventBusImpl)
    publisher = alias(source=EventBusImpl, provides=EventPublisher)
    subscriber = alias(source=EventBusImpl, provides=EventSubscriber)
    file_downloader = provide(source=AiogramFileDownloader, provides=FileDownloader)

    command = provide(source=CommandService)
    webhook = provide(source=WebhookService)

    outbound_webhook = provide(source=OutboundWebhookService)
    outbound_webhook_sender = provide(source=OutboundWebhookSender)

    remnawave = provide(source=RemnawaveImpl, provides=Remnawave)
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

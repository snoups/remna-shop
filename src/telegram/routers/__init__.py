from aiogram import Router

from . import dashboard, extra, menu, subscription


def setup_routers(router: Router) -> None:
    # WARNING: The order of router registration matters!
    routers = [
        extra.payment.router,
        extra.notification.router,
        extra.test.router,
        extra.commands.router,
        extra.member.router,
        extra.channel_member.router,
        extra.goto.router,
        extra.inline.router,
        #
        menu.handlers.router,
        menu.dialog.router,
        #
        subscription.dialog.router,
        #
        dashboard.dialog.router,
        dashboard.statistics.dialog.router,
        dashboard.access.dialog.router,
        dashboard.broadcast.dialog.router,
        dashboard.promocodes.dialog.router,
        dashboard.remnawave.dialog.router,
        #
        dashboard.remnatrishop.dialog.router,
        dashboard.remnatrishop.gateways.dialog.router,
        dashboard.remnatrishop.referral.dialog.router,
        dashboard.remnatrishop.notifications.dialog.router,
        dashboard.remnatrishop.plans.dialog.router,
        dashboard.remnatrishop.menu_editor.dialog.router,
        dashboard.remnatrishop.backup.dialog.router,
        dashboard.remnatrishop.advertising.dialog.router,
        dashboard.remnatrishop.extra.dialog.router,
        dashboard.remnatrishop.grace.dialog.router,
        #
        dashboard.users.dialog.router,
        dashboard.users.user.dialog.router,
        #
        dashboard.importer.dialog.router,
    ]

    router.include_routers(*routers)

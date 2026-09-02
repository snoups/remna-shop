from pathlib import Path


def test_lifespan_shutdown_does_not_delete_shared_telegram_configuration() -> None:
    source = Path("src/lifespan.py").read_text(encoding="utf-8")
    startup, separator, shutdown = source.partition("    yield\n")

    assert separator, "lifespan must retain its startup/shutdown boundary"

    # A replacement replica still owns setup during startup.
    assert "await webhook_service.setup_webhook(allowed_updates)" in startup
    assert "await command_service.setup_commands()" in startup

    # Webhook and command configuration is global to a Telegram bot, so an
    # individual replica must not remove it when its local lifecycle ends.
    assert "delete_webhook" not in shutdown
    assert "delete_commands" not in shutdown

    # Local shutdown notification and resource cleanup must still run.
    assert "BotShutdownEvent(" in shutdown
    assert "await event_bus.publish(bot_shutdown_event)" in shutdown
    assert "await event_bus.shutdown()" in shutdown
    assert "await notification_worker.shutdown()" in shutdown
    assert "await telegram_webhook_endpoint.shutdown()" in shutdown
    assert "await container.close()" in shutdown

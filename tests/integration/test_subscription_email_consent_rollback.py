import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="TEST_DATABASE_URL is required for PostgreSQL migration tests",
)

USER_ID = 98_500_057


@pytest.mark.asyncio
async def test_old_runtime_email_updates_clear_subscription_email_consent() -> None:
    """Statements that do not know the new columns remain rollback-compatible."""
    assert TEST_DATABASE_URL is not None
    engine = create_async_engine(TEST_DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    try:
        async with sessions() as session:
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": USER_ID})
            await session.execute(
                text(
                    """
                    INSERT INTO users (
                        id, telegram_id, name, role, language, referral_code,
                        personal_discount, purchase_discount, points, is_blocked,
                        is_bot_blocked, is_rules_accepted, is_trial_available,
                        email, is_email_verified, auth_type, token_version,
                        subscription_expiration_email_enabled,
                        subscription_expiration_email_enabled_at
                    ) VALUES (
                        :id, :telegram_id, 'rollback-probe', 'USER', 'EN',
                        :referral_code, 0, 0, 0, false, false, true, false,
                        'before@example.org', true, 'telegram', 0, true,
                        clock_timestamp()
                    )
                    """
                ),
                {
                    "id": USER_ID,
                    "telegram_id": USER_ID,
                    "referral_code": f"rollback-probe-{USER_ID}",
                },
            )
            await session.commit()

        async with sessions() as session:
            # This is the important pre-0057 shape: the old application changes
            # only identity fields and never mentions the consent columns.
            await session.execute(
                text("UPDATE users SET email = 'after@example.org' WHERE id = :id"),
                {"id": USER_ID},
            )
            await session.commit()
            changed_email = (
                await session.execute(
                    text(
                        """
                        SELECT subscription_expiration_email_enabled,
                               subscription_expiration_email_enabled_at
                        FROM users
                        WHERE id = :id
                        """
                    ),
                    {"id": USER_ID},
                )
            ).one()
            assert changed_email == (False, None)

            await session.execute(
                text(
                    """
                    UPDATE users
                    SET is_email_verified = true,
                        subscription_expiration_email_enabled = true,
                        subscription_expiration_email_enabled_at = clock_timestamp()
                    WHERE id = :id
                    """
                ),
                {"id": USER_ID},
            )
            await session.commit()

            # Explicitly writing the same verified identity must not revoke a
            # valid opt-in; only a changed address or non-TRUE verification does.
            await session.execute(
                text("UPDATE users SET is_email_verified = true WHERE id = :id"),
                {"id": USER_ID},
            )
            await session.commit()
            assert await session.scalar(
                text(
                    """
                    SELECT subscription_expiration_email_enabled
                    FROM users
                    WHERE id = :id
                    """
                ),
                {"id": USER_ID},
            ) is True

            await session.execute(
                text("UPDATE users SET is_email_verified = false WHERE id = :id"),
                {"id": USER_ID},
            )
            await session.commit()
            lost_verification = (
                await session.execute(
                    text(
                        """
                        SELECT subscription_expiration_email_enabled,
                               subscription_expiration_email_enabled_at
                        FROM users
                        WHERE id = :id
                        """
                    ),
                    {"id": USER_ID},
                )
            ).one()
            assert lost_verification == (False, None)
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(text("DELETE FROM users WHERE id = :id"), {"id": USER_ID})
            await cleanup.commit()
        await engine.dispose()

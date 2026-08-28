from typing import Sequence, Union

from alembic import op

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remnawave 2.8.0 collapsed the granular expiration events into a single
    # user.expiration webhook, so the per-threshold notification toggles are
    # gone from UserNotificationType. Strip the now-dead keys from the stored
    # settings map (the surviving EXPIRES/EXPIRED toggles default to enabled).
    op.execute(
        """
        UPDATE settings
        SET notifications = jsonb_set(
            notifications,
            '{settings}',
            (notifications -> 'settings')
                - 'EXPIRES_IN_3_DAYS'
                - 'EXPIRES_IN_2_DAYS'
                - 'EXPIRES_IN_1_DAY'
                - 'EXPIRED_1_DAY_AGO'
        )
        WHERE notifications ? 'settings'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE settings
        SET notifications = jsonb_set(
            notifications,
            '{settings}',
            (notifications -> 'settings')
                || '{"EXPIRES_IN_3_DAYS": true, "EXPIRES_IN_2_DAYS": true,
                     "EXPIRES_IN_1_DAY": true, "EXPIRED_1_DAY_AGO": true}'::jsonb
        )
        WHERE notifications ? 'settings'
        """
    )

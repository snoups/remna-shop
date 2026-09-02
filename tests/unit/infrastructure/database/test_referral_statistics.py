from datetime import UTC, datetime

from sqlalchemy import create_engine, insert, text

from src.core.enums import ReferralLevel
from src.infrastructure.database.dao.referral import ReferralDaoImpl
from src.infrastructure.database.dao.user_merge import UserMergeDaoImpl
from src.infrastructure.database.models.referral import Referral


def test_referral_levels_are_derived_from_the_attribution_graph() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, merged_into_user_id INTEGER NULL)"
            )
        )
    Referral.__table__.create(engine)
    timestamp = datetime(2026, 8, 22, tzinfo=UTC)

    # A -> B, C; B -> D, E; C -> F; D -> G. Every stored row is a
    # direct edge (FIRST), while the graph contains four L2 relationships.
    # User H was merged into B; its historical attribution must not be counted.
    rows = [
        (1, 1, 2),
        (2, 1, 3),
        (3, 2, 4),
        (4, 2, 5),
        (5, 3, 6),
        (6, 4, 7),
        (7, 1, 8),
    ]
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, merged_into_user_id) VALUES (:id, :target)"),
            [
                {"id": user_id, "target": 2 if user_id == 8 else None}
                for user_id in range(1, 9)
            ],
        )
        connection.execute(
            insert(Referral.__table__),
            [
                {
                    "id": referral_id,
                    "referrer_id": referrer_id,
                    "referred_id": referred_id,
                    "level": ReferralLevel.FIRST,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                for referral_id, referrer_id, referred_id in rows
            ],
        )

        global_stats = connection.execute(
            ReferralDaoImpl._referral_network_stats_statement()
        ).mappings().one()
        user_a_stats = connection.execute(
            ReferralDaoImpl._user_referral_network_stats_statement(1)
        ).mappings().one()
        user_b_stats = connection.execute(
            ReferralDaoImpl._user_referral_network_stats_statement(2)
        ).mappings().one()
        leaf_stats = connection.execute(
            ReferralDaoImpl._user_referral_network_stats_statement(7)
        ).mappings().one()
        ancestor_path_count = connection.scalar(
            UserMergeDaoImpl._referral_path_statement(1, 7)
        )
        reverse_path_count = connection.scalar(
            UserMergeDaoImpl._referral_path_statement(7, 1)
        )

    assert dict(global_stats) == {
        "total_referrals": 6,
        "level_1_count": 6,
        "level_2_count": 4,
        "unique_referrers": 4,
    }
    assert dict(user_a_stats) == {"level_1": 2, "level_2": 3}
    assert dict(user_b_stats) == {"level_1": 2, "level_2": 1}
    assert dict(leaf_stats) == {"level_1": 0, "level_2": 0}
    assert ancestor_path_count == 1
    assert reverse_path_count == 0

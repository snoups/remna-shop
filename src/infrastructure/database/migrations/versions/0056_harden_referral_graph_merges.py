from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


REFERRAL_GRAPH_ADVISORY_LOCK_ID = 0x524546455252414C
CANONICAL_TRIGGER_FUNCTION = "enforce_canonical_referral_edge"
CANONICAL_TRIGGER = "trg_referrals_canonical_edge"


CREATE_CANONICAL_MAP_SQL = """
CREATE TEMP TABLE remnashop_0056_user_canonical_map
ON COMMIT DROP
AS
WITH RECURSIVE merge_chain (
    source_user_id,
    current_user_id,
    merged_into_user_id,
    path
) AS (
    SELECT
        id,
        id,
        merged_into_user_id,
        ARRAY[id]
    FROM users
    WHERE merged_into_user_id IS NOT NULL

    UNION ALL

    SELECT
        chain.source_user_id,
        target.id,
        target.merged_into_user_id,
        chain.path || target.id
    FROM merge_chain AS chain
    JOIN users AS target ON target.id = chain.merged_into_user_id
    WHERE NOT target.id = ANY(chain.path)
      AND cardinality(chain.path) < 64
)
SELECT DISTINCT ON (source_user_id)
    source_user_id,
    current_user_id AS canonical_user_id
FROM merge_chain
WHERE merged_into_user_id IS NULL
ORDER BY source_user_id, cardinality(path) DESC
"""


VALIDATE_CANONICAL_MAP_SQL = """
DO $validate_user_merge_graph$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM users AS source
        LEFT JOIN remnashop_0056_user_canonical_map AS canonical
          ON canonical.source_user_id = source.id
        WHERE source.merged_into_user_id IS NOT NULL
          AND canonical.canonical_user_id IS NULL
    ) THEN
        RAISE EXCEPTION 'user merge graph has a cycle or exceeds 64 hops'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_users_merge_chain_resolvable';
    END IF;
END;
$validate_user_merge_graph$;
"""


CREATE_REPAIR_MAP_SQL = """
CREATE TEMP TABLE remnashop_0056_referral_repair
ON COMMIT DROP
AS
SELECT
    referral.id AS referral_id,
    referral.referrer_id AS previous_referrer_id,
    canonical.canonical_user_id AS canonical_referrer_id
FROM referrals AS referral
JOIN remnashop_0056_user_canonical_map AS canonical
  ON canonical.source_user_id = referral.referrer_id
WHERE referral.referrer_id <> canonical.canonical_user_id
"""


VALIDATE_PROJECTED_GRAPH_SQL = """
DO $validate_projected_referral_graph$
BEGIN
    IF EXISTS (
        WITH RECURSIVE projected_referrals AS (
            SELECT
                referral.id,
                COALESCE(canonical.canonical_user_id, referral.referrer_id) AS referrer_id,
                referral.referred_id
            FROM referrals AS referral
            LEFT JOIN remnashop_0056_user_canonical_map AS canonical
              ON canonical.source_user_id = referral.referrer_id
        ),
        descendants (root_user_id, user_id) AS (
            SELECT projected.referrer_id, projected.referred_id
            FROM projected_referrals AS projected

            UNION

            SELECT descendants.root_user_id, projected.referred_id
            FROM descendants
            JOIN projected_referrals AS projected
              ON projected.referrer_id = descendants.user_id
        )
        SELECT 1
        FROM descendants
        WHERE descendants.root_user_id = descendants.user_id
    ) THEN
        RAISE EXCEPTION
            'referral graph contains a cycle after canonical merge projection'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_referrals_acyclic';
    END IF;
END;
$validate_projected_referral_graph$;
"""


REPAIR_REFERRERS_SQL = """
UPDATE referrals AS referral
SET referrer_id = repair.canonical_referrer_id
FROM remnashop_0056_referral_repair AS repair
WHERE referral.id = repair.referral_id
"""


CREATE_TRIGGER_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {CANONICAL_TRIGGER_FUNCTION}()
RETURNS trigger
LANGUAGE plpgsql
AS $canonical_referral_edge$
DECLARE
    canonical_referrer_id integer;
    canonical_referred_id integer;
    excluded_referral_id integer;
    canonicalize_referred boolean;
    creates_cycle boolean;
BEGIN
    PERFORM pg_advisory_xact_lock({REFERRAL_GRAPH_ADVISORY_LOCK_ID});

    WITH RECURSIVE merge_chain (user_id, merged_into_user_id, path) AS (
        SELECT id, merged_into_user_id, ARRAY[id]
        FROM users
        WHERE id = NEW.referrer_id

        UNION ALL

        SELECT target.id, target.merged_into_user_id, chain.path || target.id
        FROM merge_chain AS chain
        JOIN users AS target ON target.id = chain.merged_into_user_id
        WHERE NOT target.id = ANY(chain.path)
          AND cardinality(chain.path) < 64
    )
    SELECT user_id
    INTO canonical_referrer_id
    FROM merge_chain
    WHERE merged_into_user_id IS NULL
    ORDER BY cardinality(path) DESC
    LIMIT 1;

    IF canonical_referrer_id IS NULL THEN
        RAISE EXCEPTION 'referral referrer has no canonical merge target'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_referrals_canonical_referrer';
    END IF;

    canonicalize_referred := TG_OP = 'INSERT';
    IF TG_OP = 'UPDATE' THEN
        excluded_referral_id := OLD.id;
        canonicalize_referred := NEW.referred_id IS DISTINCT FROM OLD.referred_id;
    END IF;

    IF canonicalize_referred THEN
        WITH RECURSIVE merge_chain (user_id, merged_into_user_id, path) AS (
            SELECT id, merged_into_user_id, ARRAY[id]
            FROM users
            WHERE id = NEW.referred_id

            UNION ALL

            SELECT target.id, target.merged_into_user_id, chain.path || target.id
            FROM merge_chain AS chain
            JOIN users AS target ON target.id = chain.merged_into_user_id
            WHERE NOT target.id = ANY(chain.path)
              AND cardinality(chain.path) < 64
        )
        SELECT user_id
        INTO canonical_referred_id
        FROM merge_chain
        WHERE merged_into_user_id IS NULL
        ORDER BY cardinality(path) DESC
        LIMIT 1;

        IF canonical_referred_id IS NULL THEN
            RAISE EXCEPTION 'referral recipient has no canonical merge target'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'ck_referrals_canonical_referred';
        END IF;

        NEW.referred_id := canonical_referred_id;
    END IF;

    WITH RECURSIVE descendants (user_id) AS (
        SELECT NEW.referred_id

        UNION

        SELECT referral.referred_id
        FROM descendants
        JOIN referrals AS referral
          ON referral.referrer_id = descendants.user_id
         AND referral.id IS DISTINCT FROM excluded_referral_id
    )
    SELECT EXISTS (
        SELECT 1
        FROM descendants
        WHERE user_id = canonical_referrer_id
    )
    INTO creates_cycle;

    IF creates_cycle THEN
        RAISE EXCEPTION 'referral edge would create a cycle'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_referrals_acyclic';
    END IF;

    NEW.referrer_id := canonical_referrer_id;
    RETURN NEW;
END;
$canonical_referral_edge$;
"""


CREATE_TRIGGER_SQL = f"""
CREATE TRIGGER {CANONICAL_TRIGGER}
BEFORE INSERT OR UPDATE OF referrer_id, referred_id ON referrals
FOR EACH ROW
EXECUTE FUNCTION {CANONICAL_TRIGGER_FUNCTION}()
"""


def upgrade() -> None:
    op.execute(sa.text(f"SELECT pg_advisory_xact_lock({REFERRAL_GRAPH_ADVISORY_LOCK_ID})"))
    op.execute(sa.text("LOCK TABLE referrals IN SHARE ROW EXCLUSIVE MODE"))
    op.execute(sa.text(CREATE_CANONICAL_MAP_SQL))
    op.execute(sa.text(VALIDATE_CANONICAL_MAP_SQL))
    op.execute(sa.text(CREATE_REPAIR_MAP_SQL))
    op.execute(sa.text(VALIDATE_PROJECTED_GRAPH_SQL))
    op.execute(sa.text(REPAIR_REFERRERS_SQL))
    op.execute(sa.text(CREATE_TRIGGER_FUNCTION_SQL))
    op.execute(sa.text(CREATE_TRIGGER_SQL))


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS {CANONICAL_TRIGGER} ON referrals"))
    op.execute(sa.text(f"DROP FUNCTION IF EXISTS {CANONICAL_TRIGGER_FUNCTION}()"))

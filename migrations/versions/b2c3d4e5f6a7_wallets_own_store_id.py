"""Move store ownership onto wallets and unique pub_address

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-18

"""
from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

LEGACY_DEFAULT_STORE_ID = 1
FDA_INDEX = "uq_wallets_fee_deposit_store_id"
PUB_INDEX = "uq_wallets_pub_address"
FDA_STORE_COL = "fda_store_id"


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name):
    return name in _inspector().get_table_names()


def _column_exists(table, column):
    if not _table_exists(table):
        return False
    return column in {c["name"] for c in _inspector().get_columns(table)}


def _index_exists(table, index_name):
    if not _table_exists(table):
        return False
    return any(idx["name"] == index_name for idx in _inspector().get_indexes(table))


def upgrade():
    bind = op.get_bind()

    if _table_exists("wallets") and _table_exists("accounts"):
        bind.execute(
            sa.text(
                """
                UPDATE wallets w
                INNER JOIN (
                    SELECT address, MIN(store_id) AS store_id
                    FROM accounts
                    WHERE store_id IS NOT NULL
                    GROUP BY address
                ) a ON a.address = w.pub_address
                SET w.store_id = a.store_id
                WHERE w.store_id IS NULL
                """
            )
        )
        bind.execute(
            sa.text("UPDATE wallets SET store_id = :sid WHERE store_id IS NULL"),
            {"sid": LEGACY_DEFAULT_STORE_ID},
        )

    if _index_exists("wallets", FDA_INDEX):
        op.drop_index(FDA_INDEX, table_name="wallets")

    if _table_exists("wallets") and not _column_exists("wallets", FDA_STORE_COL):
        bind.execute(
            sa.text(
                """
                ALTER TABLE wallets
                ADD COLUMN fda_store_id INT GENERATED ALWAYS AS (
                    CASE WHEN `type` = 'fee_deposit' THEN store_id ELSE NULL END
                ) VIRTUAL
                """
            )
        )

    if _table_exists("wallets") and not _index_exists("wallets", FDA_INDEX):
        op.create_index(FDA_INDEX, "wallets", [FDA_STORE_COL], unique=True)

    if _table_exists("wallets"):
        bind.execute(
            sa.text(
                """
                DELETE w1 FROM wallets w1
                INNER JOIN wallets w2
                  ON w1.pub_address = w2.pub_address AND w1.id > w2.id
                WHERE w1.pub_address IS NOT NULL
                """
            )
        )

    if _table_exists("wallets") and not _index_exists("wallets", PUB_INDEX):
        op.create_index(PUB_INDEX, "wallets", ["pub_address"], unique=True)

    if _column_exists("accounts", "store_id"):
        op.drop_column("accounts", "store_id")


def downgrade():
    if _table_exists("accounts") and not _column_exists("accounts", "store_id"):
        op.add_column("accounts", sa.Column("store_id", sa.Integer(), nullable=True))

    bind = op.get_bind()
    if _table_exists("wallets") and _table_exists("accounts"):
        bind.execute(
            sa.text(
                """
                UPDATE accounts a
                INNER JOIN wallets w ON w.pub_address = a.address
                SET a.store_id = w.store_id
                WHERE a.store_id IS NULL
                """
            )
        )

    if _index_exists("wallets", PUB_INDEX):
        op.drop_index(PUB_INDEX, table_name="wallets")

    if _index_exists("wallets", FDA_INDEX):
        op.drop_index(FDA_INDEX, table_name="wallets")

    if _column_exists("wallets", FDA_STORE_COL):
        op.drop_column("wallets", FDA_STORE_COL)

    if _table_exists("wallets"):
        bind.execute(
            sa.text(
                "UPDATE wallets SET store_id = NULL "
                "WHERE type IS NULL OR type != 'fee_deposit'"
            )
        )

    if _table_exists("wallets") and not _index_exists("wallets", FDA_INDEX):
        op.create_index(FDA_INDEX, "wallets", ["store_id"], unique=True)

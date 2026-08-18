"""Add multistore store_id support

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-08-12

"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = None
branch_labels = None
depends_on = None

LEGACY_DEFAULT_STORE_ID = 1
FDA_INDEX = "uq_wallets_fee_deposit_store_id"
PUB_INDEX = "uq_wallets_pub_address"
FDA_TYPE_COL = "fda_type"


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

    if not _table_exists("settings"):
        op.create_table(
            "settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=80), nullable=True),
            sa.Column("value", sa.String(length=250), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("id"),
        )

    if not _table_exists("accounts"):
        op.create_table(
            "accounts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("address", sa.String(length=70), nullable=True),
            sa.Column("crypto", sa.String(length=20), nullable=True),
            sa.Column(
                "amount",
                sa.Numeric(precision=52, scale=26),
                nullable=True,
                server_default="0",
            ),
            sa.Column("last_update", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=10), nullable=True),
            sa.Column("type", sa.String(length=30), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("id"),
        )

    if not _table_exists("wallets"):
        op.create_table(
            "wallets",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("pub_address", sa.String(length=70), nullable=True),
            sa.Column("priv_key", sa.String(length=300), nullable=True),
            sa.Column("create_time", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=10), nullable=True),
            sa.Column("type", sa.String(length=30), nullable=True),
            sa.Column("store_id", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("id"),
        )

    if not _column_exists("wallets", "store_id"):
        op.add_column("wallets", sa.Column("store_id", sa.Integer(), nullable=True))

    bind.execute(
        sa.text("UPDATE wallets SET store_id = :sid WHERE store_id IS NULL"),
        {"sid": LEGACY_DEFAULT_STORE_ID},
    )

    if not _column_exists("wallets", FDA_TYPE_COL):
        bind.execute(
            sa.text(
                """
                ALTER TABLE wallets
                ADD COLUMN fda_type VARCHAR(30) GENERATED ALWAYS AS (
                    CASE WHEN `type` = 'fee_deposit' THEN `type` ELSE NULL END
                ) VIRTUAL
                """
            )
        )

    if not _index_exists("wallets", FDA_INDEX):
        op.create_index(
            FDA_INDEX, "wallets", ["store_id", FDA_TYPE_COL], unique=True
        )

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

    if not _index_exists("wallets", PUB_INDEX):
        op.create_index(PUB_INDEX, "wallets", ["pub_address"], unique=True)


def downgrade():
    if _index_exists("wallets", PUB_INDEX):
        op.drop_index(PUB_INDEX, table_name="wallets")

    if _index_exists("wallets", FDA_INDEX):
        op.drop_index(FDA_INDEX, table_name="wallets")

    if _column_exists("wallets", FDA_TYPE_COL):
        op.drop_column("wallets", FDA_TYPE_COL)

    if _column_exists("wallets", "store_id"):
        op.drop_column("wallets", "store_id")

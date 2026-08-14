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
INDEX_NAME = "uq_wallets_fee_deposit_store_id"


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
            sa.Column("store_id", sa.Integer(), nullable=True),
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

    if not _column_exists("accounts", "store_id"):
        op.add_column("accounts", sa.Column("store_id", sa.Integer(), nullable=True))

    if not _column_exists("wallets", "store_id"):
        op.add_column("wallets", sa.Column("store_id", sa.Integer(), nullable=True))

    bind = op.get_bind()
    default_store_id = bind.execute(
        sa.text(
            """
            SELECT COALESCE(
                (SELECT store_id
                 FROM wallets
                 WHERE type = 'fee_deposit' AND store_id IS NOT NULL
                 ORDER BY id ASC
                 LIMIT 1),
                (SELECT store_id
                 FROM accounts
                 WHERE store_id IS NOT NULL
                 ORDER BY id ASC
                 LIMIT 1),
                :legacy_default
            ) AS sid
            """
        ),
        {"legacy_default": LEGACY_DEFAULT_STORE_ID},
    ).scalar()

    bind.execute(
        sa.text("UPDATE accounts SET store_id = :sid WHERE store_id IS NULL"),
        {"sid": int(default_store_id)},
    )
    bind.execute(
        sa.text(
            "UPDATE wallets SET store_id = :sid "
            "WHERE store_id IS NULL AND type = 'fee_deposit'"
        ),
        {"sid": int(default_store_id)},
    )

    if not _index_exists("wallets", INDEX_NAME):
        op.create_index(INDEX_NAME, "wallets", ["store_id"], unique=True)


def downgrade():
    if _index_exists("wallets", INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="wallets")

    if _column_exists("wallets", "store_id"):
        op.drop_column("wallets", "store_id")

    if _column_exists("accounts", "store_id"):
        op.drop_column("accounts", "store_id")

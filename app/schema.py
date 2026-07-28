"""Idempotent column upgrades for existing databases.

db.create_all() only creates missing tables — it does not ADD columns.
"""

from sqlalchemy import inspect, text

from .db_import import db
from .logging import logger


def _has_column(table: str, column: str) -> bool:
    insp = inspect(db.engine)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def _has_index(table: str, index_name: str) -> bool:
    insp = inspect(db.engine)
    if table not in insp.get_table_names():
        return False
    return any(idx["name"] == index_name for idx in insp.get_indexes(table))


def ensure_schema():
    statements = []
    if not _has_column("accounts", "fda_key"):
        statements.append(
            "ALTER TABLE accounts ADD COLUMN fda_key VARCHAR(128) NULL"
        )
    if not _has_column("wallets", "fda_key"):
        statements.append(
            "ALTER TABLE wallets ADD COLUMN fda_key VARCHAR(128) NULL"
        )
    if not _has_column("accounts", "sweep_target"):
        statements.append(
            "ALTER TABLE accounts ADD COLUMN sweep_target VARCHAR(70) NULL"
        )

    with db.engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))

        if _has_column("wallets", "fda_key") and not _has_index(
            "wallets", "uq_wallets_fee_deposit_fda_key"
        ):
            # Unique on fda_key: only fee_deposit rows set it; NULLs stay allowed
            # for regular wallets (MySQL/MariaDB treat NULL as distinct).
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX uq_wallets_fee_deposit_fda_key "
                    "ON wallets (fda_key)"
                )
            )
            logger.info("Created unique index uq_wallets_fee_deposit_fda_key")

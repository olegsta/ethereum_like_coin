import sqlite3

import pytest


DDL = """
CREATE TABLE wallets (
    id INTEGER PRIMARY KEY,
    pub_address TEXT,
    type TEXT,
    store_id INTEGER,
    fda_type TEXT GENERATED ALWAYS AS (
        CASE WHEN type = 'fee_deposit' THEN type ELSE NULL END
    ) VIRTUAL
);
CREATE UNIQUE INDEX uq_wallets_fee_deposit_store_id
    ON wallets (store_id, fda_type);
"""


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL)
    yield conn
    conn.close()


def _insert(conn, address, wallet_type, store_id):
    conn.execute(
        "INSERT INTO wallets (pub_address, type, store_id) VALUES (?, ?, ?)",
        (address, wallet_type, store_id),
    )


def test_many_regular_wallets_share_a_store(db):
    _insert(db, "0xreg1", "regular", 1)
    _insert(db, "0xreg2", "regular", 1)
    assert db.execute("SELECT COUNT(*) FROM wallets").fetchone()[0] == 2


def test_one_fee_deposit_per_store(db):
    _insert(db, "0xfda1", "fee_deposit", 1)
    with pytest.raises(sqlite3.IntegrityError):
        _insert(db, "0xfda1b", "fee_deposit", 1)


def test_fee_deposit_per_store_is_independent(db):
    _insert(db, "0xfda1", "fee_deposit", 1)
    _insert(db, "0xfda2", "fee_deposit", 2)
    _insert(db, "0xreg", "regular", 1)
    rows = db.execute(
        "SELECT pub_address, type, store_id, fda_type FROM wallets ORDER BY id"
    ).fetchall()
    assert rows == [
        ("0xfda1", "fee_deposit", 1, "fee_deposit"),
        ("0xfda2", "fee_deposit", 2, "fee_deposit"),
        ("0xreg", "regular", 1, None),
    ]

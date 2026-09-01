"""Reproduction of the BNB payout PendingRollbackError.

Celery reuses one Flask-SQLAlchemy Session. A dead DB connection leaves it
invalid; the next make_multipayout FDA lookup must still return the address.

Uses a file-backed sqlite DB so reconnect keeps tables (like MariaDB).
In-memory sqlite:// is empty after connection.invalidate().
"""
import os
import tempfile
from unittest.mock import patch

from flask import Flask
from sqlalchemy import text

from app.db_import import db
from app.models import Wallets
from app.services.fda import get_fda_address


FDA = "0x38C488814CC92BA33307Ed6C5B68cB0b272f50A4"


def _worker_app(db_path):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {"check_same_thread": False},
    }
    db.init_app(app)
    return app


def test_get_fda_address_after_stale_connection():
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    with patch.object(db, "_engine_options", {}):
        try:
            app = _worker_app(db_path)
            with app.app_context():
                db.create_all()
                db.session.add(
                    Wallets(
                        pub_address=FDA,
                        priv_key="enc",
                        type="fee_deposit",
                        store_id=1,
                    )
                )
                db.session.commit()

                # Previous celery task: connection died mid-transaction.
                db.session.execute(text("SELECT 1"))
                db.session.connection().invalidate()

                # Same stack as make_multipayout → get_fee_deposit_account.
                assert get_fda_address(store_id=1) == FDA
        finally:
            if "app" in locals():
                with app.app_context():
                    db.session.remove()
                    db.engine.dispose()
            os.unlink(db_path)

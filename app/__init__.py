from celery import Celery
from celery.signals import task_prerun, task_postrun
from flask import Flask, has_app_context
import threading

import flask_migrate

# import flask_sqlalchemy


from sqlalchemy import text

from . import events  # noqa: F401
from .config import config
from .db_import import db
from .logging import logger

migrate = flask_migrate.Migrate()


celery = Celery(
    __name__,
    broker=f'redis://{config["REDIS_HOST"]}',
    backend=f'redis://{config["REDIS_HOST"]}',
    task_serializer="pickle",
    accept_content=["pickle"],
    result_serializer="pickle",
    result_accept_content=["pickle"],
)


def _reset_celery_db_session(**_kwargs):
    if not has_app_context():
        return
    try:
        db.session.rollback()
    except Exception:
        logger.warning("Failed to rollback DB session before task", exc_info=True)
        try:
            db.session.remove()
        except Exception:
            logger.warning("Failed to remove DB session before task", exc_info=True)


def _remove_celery_db_session(**_kwargs):
    """Close the worker Session so the next task does not reuse a dead connection."""
    if not has_app_context():
        return
    try:
        db.session.remove()
    except Exception:
        logger.warning("Failed to remove DB session after task", exc_info=True)


task_prerun.connect(_reset_celery_db_session)
task_postrun.connect(_remove_celery_db_session)


_db_bootstrapped = False
_db_bootstrap_lock = threading.Lock()


def _upgrade_schema():
    lock_name = f"{config['COIN_SYMBOL'].lower()}_schema_upgrade"
    acquired = db.session.execute(
        text("SELECT GET_LOCK(:name, :timeout)"),
        {"name": lock_name, "timeout": 60},
    ).scalar()
    if acquired != 1:
        logger.warning(
            "Could not acquire DB upgrade lock %s; skipping flask_migrate.upgrade()",
            lock_name,
        )
        return
    try:
        flask_migrate.upgrade()
    finally:
        db.session.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})


def create_app():

    app = Flask(__name__)
    app.config.from_mapping(config)

    from . import utils

    # utils.init_wallet(app)

    app.url_map.converters["decimal"] = utils.DecimalConverter

    from .api import api as api_blueprint

    app.register_blueprint(api_blueprint)

    from .api import metrics_blueprint

    app.register_blueprint(metrics_blueprint)

    db.init_app(app)
    migrate.init_app(app, db)
    with app.app_context():
        from . import models  # noqa: F401

        global _db_bootstrapped
        with _db_bootstrap_lock:
            if not _db_bootstrapped:
                db.create_all()
                _upgrade_schema()
                _db_bootstrapped = True

    return app

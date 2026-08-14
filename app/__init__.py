from celery import Celery
from flask import Flask
import threading

import flask_migrate

# import flask_sqlalchemy


from . import events  # noqa: F401
from .config import config
from .db_import import db

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

_db_bootstrapped = False
_db_bootstrap_lock = threading.Lock()


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
                flask_migrate.upgrade()
                _db_bootstrapped = True

    return app

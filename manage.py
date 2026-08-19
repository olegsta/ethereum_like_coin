#!/usr/bin/env python
import os

os.environ.setdefault("WALLET", "ETH")

from flask.cli import FlaskGroup  # noqa: E402
from flask_migrate import Migrate  # noqa: E402

from app import create_app  # noqa: E402
from app.db_import import db  # noqa: E402

app = create_app()
migrate = Migrate(app, db)
cli = FlaskGroup(create_app=create_app)

if __name__ == "__main__":
    cli()

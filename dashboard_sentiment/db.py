"""Read-only database access: engine + scoped session bound to DATABASE_URL.

Engine creation for the Flask app is deferred to `init_app()` (so `create_app()`
can load `.env` first). `create_engine_from_env()` is a standalone entrypoint
used by pre-boot scripts (`wait_for_db.py`, `verify_schema.py`) and by
`create_app()`'s own one-time scope resolution.
"""

from __future__ import annotations

import os

from flask import Flask
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

Session = scoped_session(sessionmaker(autoflush=False))


def create_engine_from_env() -> Engine:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return create_engine(database_url)


def init_app(app: Flask) -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    Session.configure(bind=engine)
    app.teardown_appcontext(lambda exception=None: Session.remove())


def is_db_reachable() -> bool:
    try:
        Session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

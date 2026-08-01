"""Shared pytest fixtures: a Postgres engine and a rollback-per-test session
so tests are fast and order-independent.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from dashboard_sentiment.models import Base

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5433/dashboard_dev"


@pytest.fixture(scope="session")
def pg_engine():
    database_url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    engine = create_engine(database_url)

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(
            "No test Postgres reachable at TEST_DATABASE_URL "
            f"({database_url}); start a local Postgres to run this suite"
        )

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(pg_engine):
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()

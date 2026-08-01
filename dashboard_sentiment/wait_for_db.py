"""Wait for the configured Postgres instance to accept connections.

Run before verify_schema.py in docker-entrypoint.sh so a freshly provisioned
database (or one still starting up) doesn't cause boot to fail outright on
its first attempt.
"""

from __future__ import annotations

import logging
import sys
import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from dashboard_sentiment.db import create_engine_from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dashboard_sentiment")

RETRY_INTERVAL_SECONDS = 2
MAX_WAIT_SECONDS = 60


def main() -> int:
    engine = create_engine_from_env()
    attempts = max(1, MAX_WAIT_SECONDS // RETRY_INTERVAL_SECONDS)

    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("Database is reachable (attempt %d/%d)", attempt, attempts)
            return 0
        except OperationalError as exc:
            logger.warning(
                "Database not reachable yet (attempt %d/%d): %s", attempt, attempts, exc
            )
            if attempt < attempts:
                time.sleep(RETRY_INTERVAL_SECONDS)

    logger.error("Database still not reachable after %d seconds, giving up", MAX_WAIT_SECONDS)
    return 1


if __name__ == "__main__":
    sys.exit(main())

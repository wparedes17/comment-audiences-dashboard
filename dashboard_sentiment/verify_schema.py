"""Fail fast, before serving traffic, if any of the 10 tables this app reads
are missing.

This app never migrates its own schema (all 10 tables are owned by the
sibling scraper's Alembic history, with the 5 Enrichment tables filled in by
the sibling Enricher). If any of them don't exist yet, the right behavior is
a clear log and a non-zero exit - not a raw ProgrammingError partway through
rendering a page.
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy import inspect

from dashboard_sentiment.db import create_engine_from_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dashboard_sentiment")

REQUIRED_TABLES = (
    "sources",
    "publications",
    "comments",
    "attachments",
    "scrape_checkpoints",
    "comment_enrichments",
    "topics",
    "comment_topics",
    "comment_summaries",
    "weekly_sentiment_stats",
)


def main() -> int:
    engine = create_engine_from_env()
    existing_tables = set(inspect(engine).get_table_names())

    missing_tables = [table for table in REQUIRED_TABLES if table not in existing_tables]
    if missing_tables:
        logger.error(
            "Missing required table(s), has the scraper's migration run yet? %s",
            ", ".join(missing_tables),
        )
        return 1

    logger.info("All %d required table(s) are present", len(REQUIRED_TABLES))
    return 0


if __name__ == "__main__":
    sys.exit(main())

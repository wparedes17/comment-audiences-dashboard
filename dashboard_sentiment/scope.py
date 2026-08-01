"""Publication scope resolution from PUBLICATION_TITLES.

See DASHBOARD_SENTIMENT.md's "Publication scope" section — same mechanism as
the Enricher's (comment-audiences-enricher's resolve_scope.py). Called once
at app startup in `app.create_app()`; the resulting publication_id set is
stored in `app.config["ALLOWED_PUBLICATION_IDS"]` and never re-resolved per
request.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dashboard_sentiment.models import Publication

logger = logging.getLogger("dashboard_sentiment")

TITLE_DELIMITER = "|"


def parse_publication_titles(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [title.strip() for title in raw_value.split(TITLE_DELIMITER) if title.strip()]


def resolve_publication_scope(session: Session, titles: list[str]) -> list[int]:
    allowed_publication_ids: set[int] = set()

    for title in titles:
        matched_ids = session.execute(
            select(Publication.id).where(
                func.lower(func.trim(Publication.title)) == func.lower(func.trim(title))
            )
        ).scalars().all()

        if not matched_ids:
            logger.warning("PUBLICATION_TITLES entry matched zero publications: %r", title)
            continue

        allowed_publication_ids.update(matched_ids)

    return sorted(allowed_publication_ids)

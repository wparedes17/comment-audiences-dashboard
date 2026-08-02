"""Flask app factory and routes for the read-only sentiment dashboard.

Reads all 10 tables (Ingestion + Enrichment) but only ever issues SELECTs —
see DASHBOARD_SENTIMENT.md for the full spec this implements. Every page only
shows data within the `PUBLICATION_TITLES` scope resolved once at startup.
"""

from __future__ import annotations

import datetime
import logging
import os

from dotenv import load_dotenv
from flask import Flask, abort, current_app, jsonify, render_template, request
from sqlalchemy import Date, and_, func, or_, select

from . import auth, db, scope
from .models import (
    Attachment,
    Comment,
    CommentEnrichment,
    CommentSummary,
    CommentTopic,
    Publication,
    Topic,
    WeeklySentimentStats,
)

logger = logging.getLogger("dashboard_sentiment")

PAGE_SIZE = 50
RELEVANT_COMMENTS_LIMIT = 10
TOP_KEYWORDS_LIMIT = 8
SUMMARY_TYPES = ("suggestions", "concerns", "agreements", "disagreements", "overview")


def _top_keywords(
    keywords: dict[str, float] | None, limit: int | None = TOP_KEYWORDS_LIMIT
) -> list[tuple[str, float]]:
    """Sort a topic's {term: weight} dict by weight descending.

    `topics.keywords` is stored as jsonb, which does not preserve insertion
    order, so the Enricher's original weight-descending order can't be
    trusted once read back - it must be re-sorted here.
    """
    if not keywords:
        return []
    ranked = sorted(keywords.items(), key=lambda pair: pair[1], reverse=True)
    return ranked[:limit] if limit is not None else ranked


def create_app() -> Flask:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app = Flask(__name__)
    db.init_app(app)
    auth.init_app(app)

    app.config["ALLOWED_PUBLICATION_IDS"] = _resolve_scope_or_fail()

    app.add_url_rule("/", view_func=overview)
    app.add_url_rule("/about", view_func=about)
    app.add_url_rule("/publications/<int:publication_id>", view_func=publication_detail)
    app.add_url_rule(
        "/publications/<int:publication_id>/daily-sentiment.json",
        view_func=publication_daily_sentiment_json,
    )
    app.add_url_rule(
        "/publications/<int:publication_id>/topics/<int:topic_id>", view_func=topic_detail_view
    )
    app.add_url_rule("/publications/<int:publication_id>/comments", view_func=publication_comments)
    app.add_url_rule("/healthz", view_func=healthz)

    return app


def _resolve_scope_or_fail() -> frozenset[int]:
    raw_titles = os.environ.get("PUBLICATION_TITLES")
    titles = scope.parse_publication_titles(raw_titles)

    session = db.Session()
    try:
        allowed_ids = scope.resolve_publication_scope(session, titles)
    finally:
        db.Session.remove()

    if not allowed_ids:
        logger.error(
            "PUBLICATION_TITLES resolved to zero publications (raw value: %r); refusing to start",
            raw_titles,
        )
        raise RuntimeError("PUBLICATION_TITLES resolved to zero publications; refusing to start.")

    return frozenset(allowed_ids)


def _allowed_publication_ids() -> frozenset[int]:
    return current_app.config["ALLOWED_PUBLICATION_IDS"]


def _get_in_scope_publication_or_404(publication_id: int) -> Publication:
    if publication_id not in _allowed_publication_ids():
        abort(404)
    publication = db.Session.get(Publication, publication_id)
    if publication is None:
        abort(404)
    return publication


def overview():
    allowed_ids = _allowed_publication_ids()

    publications = db.Session.execute(
        select(Publication).where(Publication.id.in_(allowed_ids)).order_by(Publication.title)
    ).scalars().all()

    counts_by_id = dict(
        db.Session.execute(
            select(Comment.publication_id, func.count(Comment.id))
            .where(Comment.publication_id.in_(allowed_ids))
            .group_by(Comment.publication_id)
        ).all()
    )

    latest_stats_by_id = _latest_weekly_sentiment_by_publication(allowed_ids)

    rows = [
        {
            "publication": pub,
            "comment_count": counts_by_id.get(pub.id, 0),
            "latest_sentiment": latest_stats_by_id.get(pub.id),
        }
        for pub in publications
    ]
    return render_template("overview.html", rows=rows)


def about():
    return render_template("about.html")


def _latest_weekly_sentiment_by_publication(
    publication_ids: frozenset[int],
) -> dict[int, WeeklySentimentStats]:
    latest_week_subquery = (
        select(
            WeeklySentimentStats.publication_id,
            func.max(WeeklySentimentStats.week_start_date).label("max_week_start_date"),
        )
        .where(WeeklySentimentStats.publication_id.in_(publication_ids))
        .group_by(WeeklySentimentStats.publication_id)
        .subquery()
    )
    latest_rows = db.Session.execute(
        select(WeeklySentimentStats).join(
            latest_week_subquery,
            and_(
                WeeklySentimentStats.publication_id == latest_week_subquery.c.publication_id,
                WeeklySentimentStats.week_start_date == latest_week_subquery.c.max_week_start_date,
            ),
        )
    ).scalars().all()
    return {row.publication_id: row for row in latest_rows}


def _daily_sentiment_series(publication_id: int) -> list[dict]:
    """Live day-grain sentiment rollup, computed from comments + comment_enrichments.

    Mirrors the Enricher's own weekly rollup SQL (rollup_weekly_sentiment.py's
    date_trunc/count-filter/avg pattern) but at day grain and evaluated at
    request time instead of upserted into weekly_sentiment_stats - this app
    never writes to the DB, and day grain isn't precomputed anywhere.
    """
    day = func.date_trunc("day", Comment.posted_at).cast(Date).label("day")
    rows = db.Session.execute(
        select(
            day,
            func.count(Comment.id).filter(CommentEnrichment.sentiment_label == "positive").label(
                "positive_count"
            ),
            func.count(Comment.id).filter(CommentEnrichment.sentiment_label == "neutral").label(
                "neutral_count"
            ),
            func.count(Comment.id).filter(CommentEnrichment.sentiment_label == "negative").label(
                "negative_count"
            ),
            func.avg(CommentEnrichment.sentiment_score).label("avg_sentiment_score"),
        )
        .select_from(Comment)
        .join(CommentEnrichment, CommentEnrichment.comment_id == Comment.id)
        .where(Comment.publication_id == publication_id)
        .group_by(day)
        .order_by(day)
    ).all()

    return [
        {
            "date": row.day.isoformat(),
            "positive_count": row.positive_count,
            "neutral_count": row.neutral_count,
            "negative_count": row.negative_count,
            "avg_sentiment_score": row.avg_sentiment_score,
        }
        for row in rows
    ]


def publication_detail(publication_id: int):
    publication = _get_in_scope_publication_or_404(publication_id)

    topics = db.Session.execute(
        select(Topic).where(Topic.publication_id == publication_id).order_by(Topic.created_at)
    ).scalars().all()
    topic_rows = [{"topic": topic, "top_keywords": _top_keywords(topic.keywords)} for topic in topics]

    summaries = {
        summary_type: db.Session.execute(
            select(CommentSummary)
            .where(
                CommentSummary.publication_id == publication_id,
                CommentSummary.summary_type == summary_type,
            )
            .order_by(CommentSummary.generated_at.desc())
            .limit(1)
        ).scalars().first()
        for summary_type in SUMMARY_TYPES
    }

    relevant_comments = db.Session.execute(
        select(Comment, CommentEnrichment.relevance_score)
        .join(CommentEnrichment, CommentEnrichment.comment_id == Comment.id)
        .where(
            Comment.publication_id == publication_id,
            CommentEnrichment.relevance_score.isnot(None),
        )
        .order_by(CommentEnrichment.relevance_score.desc())
        .limit(RELEVANT_COMMENTS_LIMIT)
    ).all()

    daily_sentiment = _daily_sentiment_series(publication_id)

    return render_template(
        "publication_detail.html",
        publication=publication,
        topic_rows=topic_rows,
        summaries=summaries,
        relevant_comments=relevant_comments,
        daily_sentiment=daily_sentiment,
    )


def publication_daily_sentiment_json(publication_id: int):
    _get_in_scope_publication_or_404(publication_id)
    return jsonify(_daily_sentiment_series(publication_id))


def topic_detail_view(publication_id: int, topic_id: int):
    publication = _get_in_scope_publication_or_404(publication_id)

    topic = db.Session.execute(
        select(Topic).where(Topic.id == topic_id, Topic.publication_id == publication_id)
    ).scalars().first()
    if topic is None:
        abort(404)

    comment_rows = db.Session.execute(
        select(Comment, CommentTopic.weight)
        .join(CommentTopic, CommentTopic.comment_id == Comment.id)
        .where(CommentTopic.topic_id == topic_id)
        .order_by(CommentTopic.weight.desc())
    ).all()

    return render_template(
        "topic_detail.html",
        publication=publication,
        topic=topic,
        top_keywords=_top_keywords(topic.keywords, limit=None),
        comment_rows=comment_rows,
    )


def publication_comments(publication_id: int):
    publication = _get_in_scope_publication_or_404(publication_id)

    q = request.args.get("q", "").strip()
    rows, next_cursor = _fetch_comments_page(publication_id, body_filter=q or None)

    attached_ids = _attachment_ids_for([comment.id for comment, _ in rows])

    return render_template(
        "comments.html",
        publication=publication,
        rows=rows,
        attached_ids=attached_ids,
        next_cursor=next_cursor,
        q=q,
    )


def healthz():
    if db.is_db_reachable():
        return "ok", 200
    return "database unreachable", 503


def _fetch_comments_page(publication_id: int, *, body_filter: str | None = None):
    """Keyset-paginate comments newest-first, LEFT JOINed to their sentiment label."""
    after_posted_at = request.args.get("after_posted_at")
    after_id = request.args.get("after_id", type=int)

    query = (
        select(Comment, CommentEnrichment.sentiment_label)
        .outerjoin(CommentEnrichment, CommentEnrichment.comment_id == Comment.id)
        .where(Comment.publication_id == publication_id)
    )
    if body_filter:
        query = query.where(Comment.body.ilike(f"%{body_filter}%"))

    if after_id is not None:
        if after_posted_at:
            after_dt = datetime.datetime.fromisoformat(after_posted_at)
            # NULLS LAST means every null-posted_at row sorts after every non-null one,
            # so it's unconditionally part of "the next page" once the cursor itself has
            # a real posted_at value.
            cursor_condition = or_(
                Comment.posted_at < after_dt,
                and_(Comment.posted_at == after_dt, Comment.id < after_id),
                Comment.posted_at.is_(None),
            )
        else:
            cursor_condition = and_(Comment.posted_at.is_(None), Comment.id < after_id)
        query = query.where(cursor_condition)

    query = query.order_by(Comment.posted_at.desc().nulls_last(), Comment.id.desc()).limit(
        PAGE_SIZE + 1
    )

    rows = list(db.Session.execute(query).all())
    has_next = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    next_cursor = None
    if has_next and rows:
        last_comment, _ = rows[-1]
        next_cursor = {
            "after_posted_at": last_comment.posted_at.isoformat() if last_comment.posted_at else "",
            "after_id": last_comment.id,
        }

    return rows, next_cursor


def _attachment_ids_for(comment_ids: list[int]) -> set[int]:
    if not comment_ids:
        return set()
    return set(
        db.Session.execute(
            select(Attachment.comment_id).where(Attachment.comment_id.in_(comment_ids))
        ).scalars()
    )

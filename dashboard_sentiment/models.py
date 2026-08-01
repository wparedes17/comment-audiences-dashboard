"""SQLAlchemy declarative models for the Ingestion and Enrichment bounded contexts.

See docs/SCHEMA.md for the full rationale behind each table and ARCHITECTURE.md
for how these fit into the project's layering. Ingestion tables (Source,
Publication, Comment, Attachment, ScrapeCheckpoint) hold raw scraped data.
Enrichment tables (CommentEnrichment, Topic, CommentTopic, CommentSummary,
WeeklySentimentStats) hold derived data filled in by a separate future job.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Ingestion bounded context
# ---------------------------------------------------------------------------


class Source(Base):
    """A scraped platform (this government portal, future social platforms)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.utcnow, nullable=False
    )

    publications: Mapped[list["Publication"]] = relationship(back_populates="source")


class Publication(Base):
    """The thing being commented on: a consulta pública, a post, a video, ..."""

    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_publications_source_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    opens_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closes_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    raw_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.utcnow, nullable=False
    )
    last_synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped["Source"] = relationship(back_populates="publications")
    comments: Mapped[list["Comment"]] = relationship(back_populates="publication")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="publication")
    topics: Mapped[list["Topic"]] = relationship(back_populates="publication")
    summaries: Mapped[list["CommentSummary"]] = relationship(back_populates="publication")
    weekly_sentiment_stats: Mapped[list["WeeklySentimentStats"]] = relationship(
        back_populates="publication"
    )


class Comment(Base):
    """A single raw scraped comment, unchanged from the source."""

    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint("publication_id", "external_id", name="uq_comments_publication_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    author_name: Mapped[str] = mapped_column(String(500), nullable=False)
    author_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scraped_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.utcnow, nullable=False
    )
    raw_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    publication: Mapped["Publication"] = relationship(back_populates="comments")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="comment")
    enrichment: Mapped["CommentEnrichment | None"] = relationship(
        back_populates="comment", uselist=False
    )
    topic_links: Mapped[list["CommentTopic"]] = relationship(back_populates="comment")


class Attachment(Base):
    """A file attached to a publication or to an individual comment."""

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(
            "publication_id IS NOT NULL OR comment_id IS NOT NULL",
            name="ck_attachments_publication_or_comment",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    publication_id: Mapped[int | None] = mapped_column(ForeignKey("publications.id"), nullable=True)
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    is_image: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scraped_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.utcnow, nullable=False
    )

    publication: Mapped["Publication | None"] = relationship(back_populates="attachments")
    comment: Mapped["Comment | None"] = relationship(back_populates="attachments")


class ScrapeCheckpoint(Base):
    """Bookkeeping so a run only fetches new data since the last checkpoint."""

    __tablename__ = "scrape_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "publication_id",
            "checkpoint_type",
            name="uq_scrape_checkpoints_source_publication_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    publication_id: Mapped[int | None] = mapped_column(ForeignKey("publications.id"), nullable=True)
    checkpoint_type: Mapped[str] = mapped_column(String(50), nullable=False)
    last_external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Enrichment bounded context (schema reserved now, filled by a future job)
# ---------------------------------------------------------------------------


class CommentEnrichment(Base):
    """Sentiment/relevance tags for a comment. One row per comment, 1:1."""

    __tablename__ = "comment_enrichments"

    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), primary_key=True)
    sentiment_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_suggestion: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_concern: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    stance: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    processed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    comment: Mapped["Comment"] = relationship(back_populates="enrichment")


class Topic(Base):
    """An LDA-derived topic, scoped to a single publication."""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    keywords: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.utcnow, nullable=False
    )

    publication: Mapped["Publication"] = relationship(back_populates="topics")
    comment_links: Mapped[list["CommentTopic"]] = relationship(back_populates="topic")


class CommentTopic(Base):
    """Many-to-many link between a comment and a topic, with LDA weight."""

    __tablename__ = "comment_topics"

    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False)

    comment: Mapped["Comment"] = relationship(back_populates="topic_links")
    topic: Mapped["Topic"] = relationship(back_populates="comment_links")


class CommentSummary(Base):
    """A precomputed narrative summary for the dashboard (suggestions, concerns, ...)."""

    __tablename__ = "comment_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"), nullable=False)
    summary_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.utcnow, nullable=False
    )

    publication: Mapped["Publication"] = relationship(back_populates="summaries")


class WeeklySentimentStats(Base):
    """Precomputed weekly sentiment rollup per publication, for the dashboard's
    "sentiment over time by week" view."""

    __tablename__ = "weekly_sentiment_stats"
    __table_args__ = (
        UniqueConstraint(
            "publication_id", "week_start_date", name="uq_weekly_sentiment_stats_publication_week"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"), nullable=False)
    week_start_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    positive_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    neutral_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    negative_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    publication: Mapped["Publication"] = relationship(back_populates="weekly_sentiment_stats")

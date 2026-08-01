# Database schema

This is the "documentation level" companion to the schema defined in code at
`src/scrapper_comments_audiences/infrastructure/persistence/models.py` and versioned by the
Alembic migration at `alembic/versions/0001_initial_schema.py`. See `ARCHITECTURE.md` for how these
tables map onto the project's bounded contexts and layers.

Every table lives in one of two bounded contexts:

- **Ingestion** — raw data, written by this repo's (future) scraper, never touched by anything
  else: `sources`, `publications`, `comments`, `attachments`, `scrape_checkpoints`.
- **Enrichment** — derived data, written by a separate future job that tags/analyzes what's
  already been scraped: `comment_enrichments`, `topics`, `comment_topics`, `comment_summaries`,
  `weekly_sentiment_stats`.

Splitting them this way means re-running the scraper never clobbers analysis results, and
re-running analysis never re-fetches from the source.

## Source data quirks worth remembering

The CRT portal's JSON API returns dates as `dd/mm/yyyy HH:MM` strings (e.g. `"31/07/2026 14:21"`)
with no explicit timezone. Observed values are consistent with `America/Mexico_City`. Whoever
writes the ingestion code needs to parse and localize these before storing them in the
`timestamptz` columns below — storing the naive string interpretation as UTC would silently shift
every timestamp by several hours.

## Ingestion tables

### `sources`

One row per scraped platform. `code` is the stable internal slug (e.g.
`crt_portal_consulta_publica`) a future adapter uses to identify itself; `kind` distinguishes
categories of source (e.g. `government_portal`, `social_media`) for filtering/reporting.

| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `code` | varchar(100), unique, not null | stable slug, e.g. `crt_portal_consulta_publica` |
| `name` | varchar(255), not null | human-readable name |
| `kind` | varchar(50), not null | e.g. `government_portal`, `social_media` |
| `base_url` | varchar(500), not null | root URL of the platform |
| `created_at` | timestamptz, not null | |

### `publications`

The generic "thing being commented on" — a *consulta pública* on this portal today, potentially a
post/video/thread on a future platform. Naming it generically (rather than `consultas`) is what
lets a second platform reuse this table instead of requiring a schema change.

| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `source_id` | FK → `sources.id`, not null | |
| `external_id` | varchar(100), not null | the ID at the source, e.g. `"15"` |
| `title` | text, not null | `nombre` |
| `description` | text, nullable | `objetivo` |
| `url` | varchar(1000), nullable | |
| `status` | varchar(20), nullable | derived, e.g. `open`/`closed` from `estaActiva` |
| `opens_at` | timestamptz, nullable | `fechaInicio` |
| `closes_at` | timestamptz, nullable | `fechaFin` |
| `published_at` | date, nullable | `fechaPublicacion` |
| `raw_metadata` | jsonb, nullable | full raw payload for fields not otherwise modeled (e.g. `informeConsideraciones`, whose shape hasn't been observed populated yet) |
| `first_seen_at` | timestamptz, not null | when this repo first scraped it |
| `last_synced_at` | timestamptz, nullable | when comments were last synced for it |

Unique on `(source_id, external_id)` — the same publication is never inserted twice for a source.

### `comments`

Raw scraped comments, unchanged from the source.

| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `publication_id` | FK → `publications.id`, not null | |
| `external_id` | varchar(100), not null | `id` from `GetComentarios` |
| `author_name` | varchar(500), not null | `nombreUsuario` |
| `author_external_id` | varchar(100), nullable | reserved for sources that expose a stable user ID (this portal doesn't) |
| `body` | text, not null | `comentario` |
| `posted_at` | timestamptz, nullable | `fechaCreacion`, localized (see quirks note above) |
| `scraped_at` | timestamptz, not null | when this repo fetched it |
| `raw_metadata` | jsonb, nullable | anything not otherwise modeled |

Unique on `(publication_id, external_id)`.

### `attachments`

Files attached either to a publication (e.g. the consultation's supporting documents) or to an
individual comment (e.g. a PDF a commenter attached).

| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `publication_id` | FK → `publications.id`, nullable | |
| `comment_id` | FK → `comments.id`, nullable | |
| `file_name` | varchar(500), not null | |
| `url` | varchar(1000), not null | |
| `is_image` | boolean, not null, default false | |
| `size_bytes` | integer, nullable | |
| `scraped_at` | timestamptz, not null | |

CHECK constraint: `publication_id IS NOT NULL OR comment_id IS NOT NULL` — every attachment belongs
to exactly one of the two parents.

### `scrape_checkpoints`

Bookkeeping so a scraper run only pulls what's new since the last run — this is what TO_DO.md means
by "store last commit in order new runs only update the database with new comments." The CRT
API's `GetComentarios` returns newest comments first, so an ingestion job can page from the top and
stop as soon as it sees `last_external_id` again.

| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `source_id` | FK → `sources.id`, not null | |
| `publication_id` | FK → `publications.id`, nullable | null for a source-level checkpoint (e.g. the publication *list* sync) |
| `checkpoint_type` | varchar(50), not null | e.g. `publication_list`, `comments` |
| `last_external_id` | varchar(100), nullable | newest external ID seen as of the last run |
| `last_synced_at` | timestamptz, nullable | |

Unique on `(source_id, publication_id, checkpoint_type)`.

## Enrichment tables (schema reserved now, filled by a future job)

### `comment_enrichments`

One row per comment (1:1), holding whatever a future sentiment/relevance job produces. Kept
separate from `comments` so that job can be re-run (e.g. with a better model) without touching raw
scraped data.

| Column | Type | Notes |
|---|---|---|
| `comment_id` | PK, FK → `comments.id` | |
| `sentiment_label` | varchar(20), nullable | e.g. `positive`/`neutral`/`negative` |
| `sentiment_score` | float, nullable | |
| `relevance_score` | float, nullable | drives "most relevant comments" — `ORDER BY relevance_score DESC`, no separate table needed |
| `is_suggestion` | boolean, nullable | feeds "summary of suggestions" |
| `is_concern` | boolean, nullable | feeds "summary of concerns" |
| `stance` | varchar(20), nullable | e.g. `agree`/`disagree`, feeds "elements agreed/disagreed" |
| `model_version` | varchar(100), nullable | which model/prompt produced this row |
| `processed_at` | timestamptz, nullable | |

### `topics`

An LDA-derived topic, scoped to a single publication (topics for one consultation aren't assumed to
be comparable across a different consultation).

| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `publication_id` | FK → `publications.id`, not null | |
| `label` | varchar(255), nullable | human/LLM-assigned label |
| `keywords` | jsonb, nullable | top terms with weights |
| `created_at` | timestamptz, not null | |

### `comment_topics`

Many-to-many link between comments and topics, since LDA gives a topic *distribution* per document,
not a single label.

| Column | Type | Notes |
|---|---|---|
| `comment_id` | FK → `comments.id`, part of composite PK | |
| `topic_id` | FK → `topics.id`, part of composite PK | |
| `weight` | float, not null | topic weight/probability for this comment |

### `comment_summaries`

Precomputed narrative summaries for the dashboard, per publication and per summary type — feeds
"summary of suggestions," "summary of concerns," etc. directly, without the dashboard needing to
compute anything at read time.

| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `publication_id` | FK → `publications.id`, not null | |
| `summary_type` | varchar(30), not null | `suggestions` \| `concerns` \| `agreements` \| `disagreements` \| `overview` |
| `content` | text, not null | |
| `model_version` | varchar(100), nullable | |
| `generated_at` | timestamptz, not null | |

### `weekly_sentiment_stats`

Precomputed weekly sentiment rollup per publication — feeds "sentiment analysis over the time by
week" directly.

| Column | Type | Notes |
|---|---|---|
| `id` | serial PK | |
| `publication_id` | FK → `publications.id`, not null | |
| `week_start_date` | date, not null | Monday of the ISO week |
| `positive_count` | integer, not null, default 0 | |
| `neutral_count` | integer, not null, default 0 | |
| `negative_count` | integer, not null, default 0 | |
| `avg_sentiment_score` | float, nullable | |

Unique on `(publication_id, week_start_date)`.

## What's intentionally not a table

- **Most relevant comments** — a query (`comments JOIN comment_enrichments ORDER BY
  relevance_score DESC`), not a stored table.
- **Audience/participant counts** — the CRT API's `GetParticipantesUnicos` only exposes an
  aggregate count, not per-person data, so there's no per-participant table. If tracking audience
  growth over time becomes a goal, the natural place to add it is a new snapshot table (e.g.
  `publication_metrics_snapshots`) rather than retrofitting `publications` — deferred until that's
  an actual requirement.

# Dashboard Sentiment — specification

## Purpose

The "Presentation" bounded context `ARCHITECTURE.md` explicitly called out of scope for the scraper
repo: a Flask dashboard that reads **all** of the data — both Ingestion (`sources`, `publications`,
`comments`, `attachments`) and Enrichment (`comment_enrichments`, `topics`, `comment_topics`,
`comment_summaries`, `weekly_sentiment_stats`) — to deliver the original product goals from
`README.md`:

- Sentiment analysis over time, by week
- LDA topic analysis
- Summary of suggestions raised
- Summary of concerns raised
- Summary of elements agreed/disagreed with
- The most relevant comments

Everything this dashboard shows is precomputed by the Enricher (`ENRICHER.md`) — it only ever reads
already-materialized tables. Per `ARCHITECTURE.md`'s stated intent, "the enrichment tables exist
specifically so it never has to compute anything at read time": no on-the-fly LDA, no live OpenAI
calls, no heavy aggregation queries at request time.

## Non-goals

- No write access to any table.
- No triggering the scraper or Enricher from the UI.
- No LLM calls at request time — if a summary or topic looks stale, that's the Enricher's next run
  to fix, not something this app recomputes.

## Project location

A separate repository from both the scraper and the Enricher, since it has yet another deployment
shape (long-running Service, not a Cron Job) and a different lifecycle (user-facing uptime matters
here in a way it doesn't for the batch jobs). Depends only on the shared Postgres schema.

## Publication scope

The scraper pulls every consultation the CRT portal exposes, which turned out to be a lot more than
this dashboard should actually show. This app displays **only** a configured allowlist of
publications, using the exact same mechanism as `ENRICHER.md` (they should always be pointed at the
same set, since there's no point enriching a publication this dashboard never shows, or vice versa):

- **`PUBLICATION_TITLES`** — every title to include, `|`-delimited (not comma — see `ENRICHER.md`'s
  "Publication scope" section for why titles can't safely use a comma delimiter).

**Resolving the scope.** Since this is a long-running process rather than a one-shot job, resolve
`PUBLICATION_TITLES` into a set of `publication_id`s **once at app startup** (case-insensitive,
whitespace-trimmed match against `publications.title`, identical rule to the Enricher's), and keep
that set in memory for the process's lifetime — there's no need to re-resolve it per request, since
the env var can't change without a redeploy anyway.

- An unmatched configured title logs a warning at startup, same as the Enricher.
- `PUBLICATION_TITLES` unset, or resolving to zero publications, is a startup-time configuration
  error: log it clearly and refuse to serve traffic (fail the health check / exit) rather than
  silently showing every publication in the database.

Every page below only ever shows data for this resolved set.

## Tech stack

- Flask, server-rendered Jinja2 templates, `gunicorn` in production.
- SQLAlchemy, read-only, against all 10 tables (copy the full model set from
  `scrapper-comments-audiences/src/scrapper_comments_audiences/infrastructure/persistence/
  models.py` rather than re-declaring it by hand, to avoid the two definitions drifting apart).
- A small charting library for the weekly sentiment trend (e.g. Chart.js rendered client-side from
  a JSON endpoint) — when this gets implemented, follow whatever charting/color conventions the
  rest of the org's dashboards use, if any exist by then.

## Pages

- **`/`** — overview: every publication **in the resolved scope** (never the full table) with its
  status, date range, total comment count, and a compact sentiment split (from the most recent
  `weekly_sentiment_stats` row per publication) so you can tell at a glance which consultations are
  trending negative/positive.
- **`/publications/<id>`** — the main per-consultation view. If `<id>` exists in the database but
  falls outside the resolved scope, respond 404 exactly as if it didn't exist — this dashboard
  should never leak data for a publication it wasn't configured to show, even to someone who guesses
  or bookmarks an id.
  - **Sentiment over time**: a line/stacked-area chart from `weekly_sentiment_stats` rows for this
    publication, ordered by `week_start_date` (positive/neutral/negative counts, plus
    `avg_sentiment_score`).
  - **Topics**: list `topics` for this publication with their `label` and top `keywords`; clicking
    one shows the comments most strongly linked to it via `comment_topics.weight DESC`.
  - **Summaries**: the latest `comment_summaries` row per `summary_type`
    (`ORDER BY generated_at DESC LIMIT 1`, per the Enricher's "insert-only, read latest" design —
    see `ENRICHER.md`) rendered as labeled sections: Suggestions, Concerns, Agreements,
    Disagreements, Overview.
  - **Most relevant comments**: top N by `comments JOIN comment_enrichments ORDER BY
    relevance_score DESC LIMIT N` — this is a query, not a stored table, per `docs/SCHEMA.md`'s
    "what's intentionally not a table" section.
- **`/publications/<id>/comments`** — full comment browser for this publication (same 404-if-out-of-
  scope rule as `/publications/<id>`), same shape as `COMMENT_VISUALIZER.md`'s detail page but with
  a sentiment badge per comment
  (from `comment_enrichments.sentiment_label`, when present — some comments may not be enriched
  yet, show them unlabeled rather than blocking the page).
- **`/healthz`** — DB reachability check for Northflank.

## Handling partially-enriched data

Not every comment will have a `comment_enrichments` row at all times (the Enricher runs on its own
schedule, independently of the scraper). Every enrichment-dependent element on this dashboard
(sentiment badges, "most relevant comments," summaries) must degrade gracefully — show "not yet
analyzed" rather than erroring — rather than assuming enrichment is always complete.

## Caching

Since nothing here changes except when the Enricher runs (at most a few times a day), a short
server-side cache (e.g. Flask-Caching with a 5-15 minute TTL per publication page) is a reasonable,
low-complexity way to avoid re-querying `weekly_sentiment_stats`/`topics`/`comment_summaries` on
every request — this is an optimization, not a correctness requirement, so it's fine to ship
without it first and add it if load ever justifies it.

## Access control

Unlike `COMMENT_VISUALIZER.md` (an internal debugging tool), this dashboard is arguably the
product's actual public-facing deliverable per the original goal ("so a separate dashboard can
display precomputed analysis of citizen feedback" — `README.md`). Whether it should be fully public
or behind auth is a product decision, not a technical one — make it configurable (an
`AUTH_ENABLED`/`BASIC_AUTH_*` env var pair, off by default or on by default, whichever matches the
actual intended audience) rather than hard-coding one answer.

## Config

| Env var | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string (Northflank secret; read-only role recommended) |
| `PUBLICATION_TITLES` | `\|`-delimited exact publication titles this app is allowed to show (see "Publication scope") — same value as the Enricher's |
| `AUTH_ENABLED` | whether Basic Auth is required (see "Access control") |
| `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` | credentials when `AUTH_ENABLED` is set |

## Suggested structure

```
dashboard_sentiment/
  app.py
  models.py                   # full read-only model set (all 10 tables)
  templates/
    overview.html
    publication_detail.html
    comments.html
  static/
    charts.js
  requirements.txt              # flask, sqlalchemy, psycopg2-binary, gunicorn, python-dotenv
  Dockerfile
  .env.example
```

## Deploying on Northflank

Northflank **Service**, exposed port, `/healthz` health check, `DATABASE_URL`/`PUBLICATION_TITLES`
bound as secrets/env vars (read-only Postgres role recommended, same reasoning as
`COMMENT_VISUALIZER.md`). `/healthz` should fail if `PUBLICATION_TITLES` didn't resolve to at least
one publication at startup — see "Publication scope."

## Acceptance checklist

- [ ] `/` lists only publications in the resolved `PUBLICATION_TITLES` scope, never the full table.
- [ ] `/publications/<id>` for an id that exists in the database but is outside the resolved scope
      returns 404, not the publication's data.
- [ ] `PUBLICATION_TITLES` unset, or resolving to zero publications, fails `/healthz` at startup
      rather than serving a dashboard that silently shows everything.
- [ ] One correct title and one deliberately-misspelled title in `PUBLICATION_TITLES` logs a warning
      naming the misspelled one at startup, while still serving the publication that did resolve.
- [ ] `/publications/<id>` renders a sentiment-over-time chart that matches a manual query against
      `weekly_sentiment_stats` for that publication.
- [ ] Topics list shows keywords and links through to the comments driving each topic.
- [ ] All five summary types render when present, and clearly indicate when a given type has no
      summary yet rather than erroring.
- [ ] "Most relevant comments" ordering matches a manual `ORDER BY relevance_score DESC` query.
- [ ] A publication with zero enriched comments still renders the page (empty/placeholder states,
      not a 500).
- [ ] The app issues no `INSERT`/`UPDATE`/`DELETE` statements anywhere (verify via the read-only
      Postgres role's grants).

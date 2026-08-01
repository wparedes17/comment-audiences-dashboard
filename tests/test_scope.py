from __future__ import annotations

import datetime

from dashboard_sentiment.models import Publication, Source
from dashboard_sentiment.scope import parse_publication_titles, resolve_publication_scope


def _make_source(session) -> Source:
    source = Source(
        code="crt_portal_consulta_publica",
        name="CRT Portal",
        kind="government_portal",
        base_url="https://example.gob.mx",
        created_at=datetime.datetime.utcnow(),
    )
    session.add(source)
    session.flush()
    return source


def test_parse_publication_titles_splits_trims_and_drops_empties():
    raw = " Title one | Title two|  |Title three "
    assert parse_publication_titles(raw) == ["Title one", "Title two", "Title three"]


def test_parse_publication_titles_handles_none_and_empty():
    assert parse_publication_titles(None) == []
    assert parse_publication_titles("") == []


def test_resolve_publication_scope_matches_case_insensitively(db_session):
    source = _make_source(db_session)
    publication = Publication(
        source_id=source.id,
        external_id="1",
        title="Consulta Publica de Prueba",
        first_seen_at=datetime.datetime.utcnow(),
    )
    db_session.add(publication)
    db_session.flush()

    resolved = resolve_publication_scope(db_session, ["  consulta publica de prueba  "])

    assert resolved == [publication.id]


def test_resolve_publication_scope_warns_on_unmatched_title_but_keeps_matched(db_session, caplog):
    source = _make_source(db_session)
    publication = Publication(
        source_id=source.id,
        external_id="1",
        title="Consulta Real",
        first_seen_at=datetime.datetime.utcnow(),
    )
    db_session.add(publication)
    db_session.flush()

    with caplog.at_level("WARNING"):
        resolved = resolve_publication_scope(db_session, ["Consulta Real", "Titulo Mal Escrito"])

    assert resolved == [publication.id]
    assert "Titulo Mal Escrito" in caplog.text


def test_resolve_publication_scope_returns_empty_for_no_titles(db_session):
    assert resolve_publication_scope(db_session, []) == []

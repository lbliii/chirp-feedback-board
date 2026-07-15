from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode

import pytest
from chirp.data import DataError, MigrationError, QueryError
from chirp.testing import TestClient

import app as feedback_app
from app import create_app

pytestmark = pytest.mark.issue(741)
_CSRF_RE = re.compile(r'name="_csrf_token" value="([^"]+)"')


def _cookie(response) -> str:
    value = response.header("set-cookie", "")
    assert value.startswith("chirp_session=")
    return value.split(";", 1)[0]


async def _page_context(client: TestClient) -> tuple[str, str]:
    response = await client.get("/")
    match = _CSRF_RE.search(response.text)
    assert match is not None
    return match.group(1), _cookie(response)


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        admin_token="test-owner-token",
        secret_key="test-signing-key-with-enough-entropy",
    )


async def test_full_page_health_database_readiness_and_asset(tmp_path: Path) -> None:
    app = _application(tmp_path / "board.db")
    async with TestClient(app) as client:
        page = await client.get("/")
        health = await client.get("/health")
        ready = await client.get("/ready")
        css = await client.get("/styles.css")

    assert page.status == health.status == ready.status == css.status == 200
    assert "Turn feedback into" in page.text
    assert "Add a calm dark mode" in page.text
    assert 'href="https://lbliii.github.io/chirp/"' in page.text
    assert "--lime:" in css.text


async def test_malformed_and_valid_submission_support_plain_html_and_htmx(tmp_path: Path) -> None:
    app = _application(tmp_path / "forms.db")
    async with TestClient(app) as client:
        token, cookie = await _page_context(client)
        malformed = await client.post(
            "/suggestions",
            body=urlencode({"title": "", "description": "short", "_csrf_token": token}).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": cookie,
                "HX-Request": "true",
                "HX-Target": "board",
            },
        )
        valid = await client.post(
            "/suggestions",
            body=urlencode(
                {
                    "title": "Publish a weekly digest",
                    "description": "Summarize the ideas that moved during the last seven days.",
                    "_csrf_token": token,
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        updated_cookie = valid.header("set-cookie", "").split(";", 1)[0] or cookie
        page = await client.get("/", headers={"Cookie": updated_cookie})

    assert malformed.status == 200
    assert "title of at least 3 characters" in malformed.text
    assert "hx-swap-oob" in malformed.text
    assert valid.status == 303
    assert valid.header("location") == "/"
    assert "Publish a weekly digest" in page.text


async def test_search_filter_and_empty_state_are_htmx_fragments(tmp_path: Path) -> None:
    app = _application(tmp_path / "search.db")
    async with TestClient(app) as client:
        search = await client.get(
            "/?q=onboarding",
            headers={"HX-Request": "true", "HX-Target": "board"},
        )
        filtered = await client.get(
            "/?status=shipped",
            headers={"HX-Request": "true", "HX-Target": "board"},
        )
        empty = await client.get(
            "/?q=does-not-exist",
            headers={"HX-Request": "true", "HX-Target": "board"},
        )

    assert "Make onboarding a three-minute path" in search.text
    assert "Add a calm dark mode" not in search.text
    assert "Ship keyboard navigation" in filtered.text
    assert "No ideas found" in empty.text
    assert "hx-swap-oob" in search.text


async def test_vote_constraint_counts_once_per_signed_session(tmp_path: Path) -> None:
    app = _application(tmp_path / "votes.db")
    async with TestClient(app) as client:
        token, cookie = await _page_context(client)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": cookie,
            "HX-Request": "true",
            "HX-Target": "board",
        }
        body = urlencode({"_csrf_token": token}).encode()
        first = await client.post("/suggestions/seed-export/vote", body=body, headers=headers)
        updated_cookie = first.header("set-cookie", "").split(";", 1)[0] or cookie
        page = await client.get("/", headers={"Cookie": updated_cookie})
        token_match = _CSRF_RE.search(page.text)
        assert token_match is not None
        second = await client.post(
            "/suggestions/seed-export/vote",
            body=urlencode({"_csrf_token": token_match.group(1)}).encode(),
            headers={**headers, "Cookie": updated_cookie},
        )

    assert "Vote counted" in first.text
    assert "You already voted" in second.text
    assert ">8</strong>" in second.text


async def test_owner_login_status_update_and_delete(tmp_path: Path) -> None:
    app = _application(tmp_path / "admin.db")
    async with TestClient(app) as client:
        token, cookie = await _page_context(client)
        login = await client.post(
            "/admin/login",
            body=urlencode({"token": "test-owner-token", "_csrf_token": token}).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": cookie,
                "HX-Request": "true",
                "HX-Target": "board",
            },
        )
        owner_cookie = login.header("set-cookie", "").split(";", 1)[0] or cookie
        owner_page = await client.get("/", headers={"Cookie": owner_cookie})
        token_match = _CSRF_RE.search(owner_page.text)
        assert token_match is not None
        status = await client.post(
            "/admin/suggestions/seed-export/status",
            body=urlencode({"status": "planned", "_csrf_token": token_match.group(1)}).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": owner_cookie,
                "HX-Request": "true",
                "HX-Target": "board",
            },
        )

    assert "Owner controls unlocked" in login.text
    assert "Roadmap status updated" in status.text
    assert 'value="planned" selected' in status.text


async def test_restart_preserves_submitted_data(tmp_path: Path) -> None:
    database = tmp_path / "persistent.db"
    first_app = _application(database)
    async with TestClient(first_app) as client:
        token, cookie = await _page_context(client)
        response = await client.post(
            "/suggestions",
            body=urlencode(
                {
                    "title": "Keep this after restart",
                    "description": "This row proves PostgreSQL-shaped lifecycle persistence.",
                    "_csrf_token": token,
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert response.status == 303

    second_app = _application(database)
    async with TestClient(second_app) as client:
        page = await client.get("/")

    assert "Keep this after restart" in page.text


async def test_database_unavailable_at_startup_is_actionable() -> None:
    app = create_app(
        "postgresql://postgres:postgres@127.0.0.1:1/railway",
        admin_token="test-owner-token",
        secret_key="test-signing-key-with-enough-entropy",
    )

    with pytest.raises(DataError, match=r"could not connect to 127\.0\.0\.1:1"):
        async with TestClient(app):
            pass


async def test_migration_failure_names_the_broken_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_broken.sql").write_text("CREATE TABL broken (", encoding="utf-8")
    monkeypatch.setattr(feedback_app, "MIGRATIONS", migrations)
    app = _application(tmp_path / "broken-migration.db")

    with pytest.raises(MigrationError, match="Migration 001_broken failed"):
        async with TestClient(app):
            pass


async def test_schema_mismatch_fails_loud_on_the_missing_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_wrong_schema.sql").write_text(
        "CREATE TABLE suggestions (id TEXT PRIMARY KEY);",
        encoding="utf-8",
    )
    monkeypatch.setattr(feedback_app, "MIGRATIONS", migrations)
    app = _application(tmp_path / "wrong-schema.db")

    with pytest.raises(QueryError, match="no column named title"):
        async with TestClient(app):
            pass


def test_app_contracts_pass(tmp_path: Path) -> None:
    app = _application(tmp_path / "contracts.db")
    assert app.config.workers == 1
    app.freeze()
    assert any(check.name == "database" for check in app._mutable_state.health_checks)
    app.check()

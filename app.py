"""Feedback Board: a persistent Chirp + PostgreSQL starter for Railway."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from chirp import OOB, App, AppConfig, Fragment, MutationResult, Page, Request, Response
from chirp.data import PageResult, QueryError
from chirp.middleware.sessions import get_session
from chirp.middleware.stack import secure_stack

ROOT = Path(__file__).parent
MIGRATIONS = ROOT / "migrations"
STATUSES = ("open", "planned", "in_progress", "shipped")
PER_PAGE = 6
MAX_TITLE_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 600


@dataclass(frozen=True, slots=True)
class Suggestion:
    id: str
    title: str
    description: str
    status: str
    vote_count: int
    created_at: str
    updated_at: str


SEED_SUGGESTIONS = (
    Suggestion(
        "seed-dark-mode",
        "Add a calm dark mode",
        "Offer a low-contrast theme that follows the visitor's system preference.",
        "planned",
        18,
        "2026-07-11T14:00:00+00:00",
        "2026-07-13T09:30:00+00:00",
    ),
    Suggestion(
        "seed-onboarding",
        "Make onboarding a three-minute path",
        "Turn the first visit into a short checklist with one clear success moment.",
        "in_progress",
        12,
        "2026-07-10T17:15:00+00:00",
        "2026-07-14T11:45:00+00:00",
    ),
    Suggestion(
        "seed-export",
        "Export the roadmap as CSV",
        "Let project owners take suggestions and status history into their own tools.",
        "open",
        7,
        "2026-07-12T08:20:00+00:00",
        "2026-07-12T08:20:00+00:00",
    ),
    Suggestion(
        "seed-keyboard",
        "Ship keyboard navigation",
        "Make every filter, suggestion, and moderation action reachable without a mouse.",
        "shipped",
        23,
        "2026-07-08T16:40:00+00:00",
        "2026-07-14T13:10:00+00:00",
    ),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _positive_int(raw: str | None, default: int = 1) -> int:
    try:
        return max(1, int(raw or default))
    except ValueError:
        return default


def create_app(
    database_url: str | None = None,
    *,
    admin_token: str | None = None,
    secret_key: str | None = None,
) -> App:
    """Build an isolated application for production or tests."""

    config = AppConfig.from_env(
        template_dir=ROOT / "templates",
        worker_mode="async",
        workers=1,
        htmx=True,
    )
    if secret_key:
        config = replace(config, secret_key=secret_key)
    if not config.secret_key:
        config = replace(config, secret_key="feedback-board-local-signing-key")

    resolved_admin_token = admin_token or os.environ.get("CHIRP_ADMIN_TOKEN")
    if not resolved_admin_token:
        if config.env != "development":
            raise RuntimeError("CHIRP_ADMIN_TOKEN is required outside development")
        resolved_admin_token = "feedback-board-local-admin"

    resolved_database_url = database_url or os.environ.get(
        "DATABASE_URL", f"sqlite:///{ROOT / 'feedback-board.db'}"
    )
    application = App(
        config,
        db=resolved_database_url,
        migrations=str(MIGRATIONS),
    )
    for middleware in secure_stack(application.config):
        application.add_middleware(middleware)

    @application.on_startup
    async def seed_board() -> None:
        count = int(await application.db.fetch_val("SELECT COUNT(*) FROM suggestions") or 0)
        if count:
            return
        await application.db.execute_many(
            "INSERT INTO suggestions "
            "(id, title, description, status, vote_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    item.id,
                    item.title,
                    item.description,
                    item.status,
                    item.vote_count,
                    item.created_at,
                    item.updated_at,
                )
                for item in SEED_SUGGESTIONS
            ],
        )

    def is_admin() -> bool:
        return get_session().get("feedback_admin") is True

    def voter_hash() -> str:
        session = get_session()
        voter_key = session.get("feedback_voter_key")
        if not isinstance(voter_key, str) or len(voter_key) < 20:
            voter_key = secrets.token_urlsafe(24)
            session["feedback_voter_key"] = voter_key
        return hmac.new(
            application.config.secret_key.encode(),
            voter_key.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def board_page(q: str, status: str, page: int) -> PageResult[Suggestion]:
        selected_status = status if status in STATUSES else "all"
        clauses: list[str] = []
        params: list[Any] = []
        if selected_status != "all":
            clauses.append("status = ?")
            params.append(selected_status)
        clean_query = q.strip()[:100]
        if clean_query:
            clauses.append("LOWER(title || ' ' || description) LIKE ?")
            params.append(f"%{clean_query.lower()}%")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        total = int(
            await application.db.fetch_val(f"SELECT COUNT(*) FROM suggestions{where}", *params) or 0
        )
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        selected_page = min(max(1, page), total_pages)
        items = await application.db.fetch(
            Suggestion,
            f"SELECT id, title, description, status, vote_count, created_at, updated_at "
            f"FROM suggestions{where} "
            "ORDER BY vote_count DESC, created_at DESC, id ASC LIMIT ? OFFSET ?",
            *params,
            PER_PAGE,
            (selected_page - 1) * PER_PAGE,
        )
        return PageResult(items, selected_page, PER_PAGE, total)

    async def stats() -> dict[str, int]:
        values = {
            status: int(
                await application.db.fetch_val(
                    "SELECT COUNT(*) FROM suggestions WHERE status = ?", status
                )
                or 0
            )
            for status in STATUSES
        }
        values["total"] = sum(values.values())
        return values

    async def context(
        *,
        q: str = "",
        status: str = "all",
        page: int = 1,
        notice: str = "",
    ) -> dict[str, Any]:
        selected_status = status if status in STATUSES else "all"
        return {
            "admin": is_admin(),
            "notice": notice,
            "page": await board_page(q, selected_status, page),
            "q": q.strip()[:100],
            "selected_status": selected_status,
            "stats": await stats(),
            "statuses": STATUSES,
        }

    async def result(notice: str) -> MutationResult:
        current = await context(notice=notice)
        return MutationResult(
            "/",
            Fragment("index.html", "board", **current),
            Fragment("index.html", "stats", target="stats", **current),
            Fragment("index.html", "notice", target="notice", **current),
            trigger="feedbackChanged",
        )

    @application.route("/", name="home")
    async def index(request: Request) -> Page | OOB:
        q = request.query.get("q", "") or ""
        status = request.query.get("status", "all") or "all"
        page = _positive_int(request.query.get("page"))
        current = await context(q=q, status=status, page=page)
        if request.is_narrow_fragment:
            return OOB(
                Fragment("index.html", "board", **current),
                Fragment("index.html", "stats", target="stats", **current),
            )
        return Page("index.html", "board", page_block_name="page_root", **current)

    @application.route("/suggestions", methods=["POST"], name="suggestions.add")
    async def add_suggestion(request: Request) -> MutationResult:
        form = await request.form()
        title = str(form.get("title") or "").strip()
        description = str(form.get("description") or "").strip()
        if len(title) < 3:
            return await result("Give the suggestion a title of at least 3 characters.")
        if len(title) > MAX_TITLE_LENGTH:
            return await result(f"Keep the title under {MAX_TITLE_LENGTH} characters.")
        if len(description) < 10:
            return await result("Add at least 10 characters so people understand the idea.")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            return await result(f"Keep the description under {MAX_DESCRIPTION_LENGTH} characters.")
        now = _now()
        await application.db.execute(
            "INSERT INTO suggestions "
            "(id, title, description, status, vote_count, created_at, updated_at) "
            "VALUES (?, ?, ?, 'open', 0, ?, ?)",
            uuid4().hex,
            title,
            description,
            now,
            now,
        )
        return await result(f"Added “{title}” to the board.")

    @application.route(
        "/suggestions/{suggestion_id}/vote", methods=["POST"], name="suggestions.vote"
    )
    async def vote(suggestion_id: str) -> MutationResult:
        exists = await application.db.fetch_val(
            "SELECT 1 FROM suggestions WHERE id = ?", suggestion_id
        )
        if not exists:
            return await result("That suggestion is no longer on the board.")
        key_hash = voter_hash()
        already_voted = await application.db.fetch_val(
            "SELECT 1 FROM votes WHERE suggestion_id = ? AND voter_key_hash = ?",
            suggestion_id,
            key_hash,
        )
        if already_voted:
            return await result("You already voted for that suggestion.")
        try:
            async with application.db.transaction():
                await application.db.execute(
                    "INSERT INTO votes (suggestion_id, voter_key_hash, created_at) "
                    "VALUES (?, ?, ?)",
                    suggestion_id,
                    key_hash,
                    _now(),
                )
                await application.db.execute(
                    "UPDATE suggestions SET vote_count = vote_count + 1, updated_at = ? "
                    "WHERE id = ?",
                    _now(),
                    suggestion_id,
                )
        except QueryError:
            raced_vote = await application.db.fetch_val(
                "SELECT 1 FROM votes WHERE suggestion_id = ? AND voter_key_hash = ?",
                suggestion_id,
                key_hash,
            )
            if not raced_vote:
                raise
            return await result("You already voted for that suggestion.")
        return await result("Vote counted. Thanks for shaping the roadmap.")

    @application.route("/admin/login", methods=["POST"], name="admin.login")
    async def admin_login(request: Request) -> MutationResult:
        form = await request.form()
        supplied = str(form.get("token") or "")
        if hmac.compare_digest(supplied, resolved_admin_token):
            get_session()["feedback_admin"] = True
            return await result("Owner controls unlocked for this browser.")
        return await result("That owner token was not accepted.")

    @application.route("/admin/logout", methods=["POST"], name="admin.logout")
    async def admin_logout() -> MutationResult:
        get_session().pop("feedback_admin", None)
        return await result("Owner controls locked.")

    @application.route(
        "/admin/suggestions/{suggestion_id}/status",
        methods=["POST"],
        name="admin.status",
    )
    async def update_status(request: Request, suggestion_id: str) -> MutationResult:
        if not is_admin():
            return await result("Unlock owner controls before changing roadmap status.")
        form = await request.form()
        status = str(form.get("status") or "")
        if status not in STATUSES:
            return await result("Choose a supported roadmap status.")
        changed = await application.db.execute(
            "UPDATE suggestions SET status = ?, updated_at = ? WHERE id = ?",
            status,
            _now(),
            suggestion_id,
        )
        return await result(
            "Roadmap status updated." if changed else "That suggestion is no longer on the board."
        )

    @application.route(
        "/admin/suggestions/{suggestion_id}/delete",
        methods=["POST"],
        name="admin.delete",
    )
    async def delete_suggestion(suggestion_id: str) -> MutationResult:
        if not is_admin():
            return await result("Unlock owner controls before deleting suggestions.")
        deleted = await application.db.execute(
            "DELETE FROM suggestions WHERE id = ?", suggestion_id
        )
        return await result(
            "Suggestion deleted." if deleted else "That suggestion is no longer on the board."
        )

    @application.route("/styles.css", referenced=True)
    def styles(request: Request) -> Response:
        return Response(
            (ROOT / "styles.css").read_text(encoding="utf-8"),
            content_type="text/css; charset=utf-8",
        )

    return application


app = create_app()


if __name__ == "__main__":
    app.run()

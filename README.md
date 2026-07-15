# Chirp Feedback Board

A focused feedback and public-roadmap application powered by
[Chirp](https://github.com/lbliii/chirp) and PostgreSQL. It is designed for a
zero-input Railway deployment: the template provisions the database, generates
the application and administrator secrets, runs migrations before promotion,
and checks database readiness.

Visitors can submit suggestions, search and filter the roadmap, and vote once
per suggestion. The deployer can sign in with the generated administrator token
to move suggestions through the roadmap or delete them. Every workflow has a
plain HTML form path and an enhanced HTMX path.

## Run locally

Python 3.14 and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync --frozen
uv run python app.py
```

The local app uses `feedback-board.db`. Production requires:

```text
DATABASE_URL=postgresql://...
CHIRP_ENV=production
CHIRP_SECRET_KEY=<generated signing secret>
CHIRP_ADMIN_TOKEN=<generated moderation token>
```

Open <http://127.0.0.1:8000>. The local-only administrator token is
`feedback-board-local-admin`; change it with `CHIRP_ADMIN_TOKEN` whenever the
app is reachable by anyone else.

## Deploy on Railway

[Deploy the Railway template](https://railway.com/deploy/chirp-feedback-board).
Its topology is intentionally small:

- one Chirp web service pinned to one worker;
- one Railway-managed PostgreSQL service;
- generated signing and administrator secrets;
- `chirp migrate` as the pre-deploy command;
- `/ready` as the deployment healthcheck.

Redis is not part of this product. PostgreSQL owns durable state and Chirp's
signed cookie sessions do not need a server-side session store. Add shared
runtime infrastructure only if you later scale to multiple web replicas and
introduce shared rate limits/cache, cross-worker realtime fan-out, or a
separate job queue.

See the [live demo](https://web-production-4a10d4.up.railway.app/) or read the
[Chirp documentation](https://lbliii.github.io/chirp/).

## Verify

```bash
uv run ruff check .
uv run ruff format . --check
uv run pytest -q
```

The catalog conformance workflow also checks full-page and HTMX navigation,
malformed and valid forms, one-vote constraints, assets, liveness, readiness,
restart persistence, deployment updates, rollback, and clean ejection.

## Data and rollback boundary

Migrations are forward-only and must stay backward-compatible with the previous
application release. Rolling back a Railway deployment does not roll back data.
Take or verify a PostgreSQL backup before a destructive schema change; this
starter deliberately ships no destructive migration.

## Support

Report starter problems in this repository. Chirp framework problems belong in
the [Chirp issue tracker](https://github.com/lbliii/chirp/issues).

## License

MIT

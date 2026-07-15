# Deploy and Host a Feedback & Roadmap Board with Chirp

Launch a polished public feedback board and product roadmap powered by Chirp and PostgreSQL. Visitors can submit ideas, search and filter the roadmap, and vote once per suggestion. The generated administrator token unlocks lightweight moderation for moving ideas through the roadmap or removing them.

## About Hosting

The template provisions one Chirp web service and one Railway-managed PostgreSQL service. Railway generates the application signing key and administrator token, supplies the database URL, runs database migrations before each release is promoted, and checks `/ready` before routing traffic to the new deployment.

The application uses server-rendered HTML with HTMX enhancements, so every core workflow also works without JavaScript. PostgreSQL owns all durable state. Redis is not required for this single-replica starter because Chirp uses signed cookie sessions and the application does not depend on a shared cache, job queue, or cross-worker realtime fan-out.

## Why Deploy

- Start from a useful production-shaped Chirp application instead of a hello world.
- Get a database, generated secrets, migrations, and readiness checks without manual wiring.
- Keep a simple two-service topology with a clear path to ejection and customization.
- Exercise full-page forms and HTMX fragments from the same typed Chirp handlers.
- Own the application code and PostgreSQL data after deployment.

## Common Use Cases

- Public product feedback and feature requests
- Lightweight public roadmaps
- Internal idea boards and voting queues
- A production-ready Chirp learning project
- A starting point for customer portals and community tools

## Dependencies for Chirp Feedback Board

### Deployment Dependencies

- A Chirp web service built from `lbliii/chirp-feedback-board`
- Railway PostgreSQL with a persistent volume
- Python 3.14 and the application dependencies locked in the repository

No Redis service or external SaaS account is required. After deployment, open the generated public domain to use the board. Retrieve `CHIRP_ADMIN_TOKEN` from the web service variables when you need moderator access.

Framework documentation: https://lbliii.github.io/chirp/

Starter source and support: https://github.com/lbliii/chirp-feedback-board

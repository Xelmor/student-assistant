# Production Deployment

## Goal

Use PostgreSQL in production so accounts and data are not lost after server restarts or redeploys.

## Environment variables

Set these variables on the server:

```text
APP_ENV=production
SECRET_KEY=<long-random-secret-at-least-32-chars>
COOKIE_SECURE=true
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
HOST=0.0.0.0
PORT=10000
RELOAD=false
ALLOW_LOCAL_PRIVATE_DATA=false
```

Notes:

- `postgres://...` URLs are also supported and converted automatically.
- Keep SQLite only for local development.
- Do not use `sqlite:///./student_assistant.db` on ephemeral hosting if you need persistent users.

## Render

1. Create a PostgreSQL database in Render.
2. Open the web service settings.
3. Copy the database `External Database URL` into `DATABASE_URL`.
4. Set `APP_ENV=production`.
5. Set `COOKIE_SECURE=true`.
6. Set a long random `SECRET_KEY`.
7. Redeploy the service.

## Local development

For local development you can keep:

```text
APP_ENV=development
COOKIE_SECURE=false
DATABASE_URL=sqlite:///./student_assistant.db
```

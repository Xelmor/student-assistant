# Production Deployment

## Goal

Use PostgreSQL in production so accounts and data are not lost after server restarts or redeploys.

## Environment variables

Set these variables on the server:

```text
APP_ENV=production
SECRET_KEY=<long-random-secret-at-least-32-chars>
COOKIE_SECURE=true
SESSION_MAX_AGE_SECONDS=43200
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
HOST=0.0.0.0
ALLOWED_HOSTS=student-assistant.example.com
PUBLIC_BASE_URL=https://student-assistant.example.com
PORT=8000
RELOAD=false
ALLOW_LOCAL_PRIVATE_DATA=false
```

Notes:

- `postgres://...` URLs are also supported and converted automatically.
- Keep SQLite only for local development.
- Set `ALLOWED_HOSTS` to the exact public hostname. Do not use `*`.
- Set `PUBLIC_BASE_URL` to the public HTTPS origin used in password-reset emails.
- Do not use `sqlite:///./data/student_assistant.db` on ephemeral hosting if you need persistent users.
- The app should bind to the value from `PORT`. On Render this variable is usually provided by the platform, so do not couple the deployment flow to a hard-coded port like `10000`.

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
DATABASE_URL=sqlite:///./data/student_assistant.db
```

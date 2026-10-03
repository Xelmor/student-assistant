# Production Deployment

## Goal

Use PostgreSQL in production so accounts and data are not lost after server restarts or redeploys.

## Dependency installation and lock regeneration

### Local development

Use a local virtual environment and `python -m pip install -r requirements.txt`.
This file declares direct application dependencies, including the existing password
and email validation libraries. Test tooling is declared in `requirements-dev.txt`.
Do not update an existing working environment merely to regenerate the lock.

### Production installation

`requirements.lock.txt` is resolved for **Linux x86_64 (glibc), CPython 3.12**,
matching the Python version in the current Dockerfile. It is not a universal
Windows/macOS or Linux ARM lock. Every runtime package is pinned and hashed;
pytest, Playwright and audit tooling are excluded. QR SVG uses `qrcode` and the
standard-library XML implementation; Pillow is not required for this path.

Install into an empty environment on the target platform:

```bash
python -m pip install --require-hashes -r requirements.lock.txt
python -m pip check
```

The production-lock has passed the Linux and isolated Docker checks in PR #1.
The main Dockerfile now installs this same lock with `--require-hashes`, runs
`python -m pip check`, and retains `CMD ["python", "run.py"]`.
The independent `production-image` CI job builds the **main** Dockerfile for
`linux/amd64`, checks runtime pins and QR SVG, and starts the default command
with temporary SQLite before probing HTTP through a published loopback port.
This new main-image check must pass on GitHub; earlier `Dockerfile.ci` results
do not substitute for it. See [Linux CI](testing/LINUX_CI.md).

```bash
docker build --platform linux/amd64 -t student-assistant .
docker run --rm --env-file .env -e HOST=0.0.0.0 -p 127.0.0.1:8000:8000 student-assistant
```

Local `.env`, databases, virtual environments and Git metadata are excluded from
the build context. Supply runtime settings explicitly; use PostgreSQL or a
separate SQLite volume for persistent data. The existing Render deployment mode
and service settings are unchanged; this does not claim a Render rollout.

Initial verification, before the E2E fix (macOS arm64 / CPython 3.12.14): production and dev
`pip check` passed; all 37 runtime pins remained unchanged after dev installation;
repeat lock generation was byte-for-byte identical. The primary suite passed
221 tests and 54 subtests. The complete Chromium E2E suite passed 31 tests and
failed two existing `test_entry_cta.py` cases (1440px / 390px): they expect
`/dashboard`, but the page remains at `/start`. Both failures were reproduced
against the untouched starting commit `e1217d2` in a disposable checkout using
the same clean test environment. No tests were skipped, xfailed or deleted.
Validated dev tools: pytest 9.0.3, Playwright 1.60.0, pytest-playwright 0.8.0,
httpx2 2.13.1. Dev tools themselves are not production-locked.

For startup verification, use a disposable checkout without `.env` or user data,
a temporary SQLite database, a separate test-only `SECRET_KEY`, `APP_ENV=test`,
`TESTING=true`, `DISABLE_TELEGRAM=true`, `COOKIE_SECURE=false`, `RELOAD=false`,
`HOST=127.0.0.1`, and an unused local port. Do not connect the smoke test to
production PostgreSQL, Telegram or SMTP. Preserve the real application's existing
`SECRET_KEY` and `.env`.

### Testing with runtime constraints

Use a second empty environment (these commands assume Linux/Python 3.12):

```bash
python3.12 -m venv /tmp/student-assistant-tests
source /tmp/student-assistant-tests/bin/activate
python -m pip install --require-hashes -r requirements.lock.txt
python -m pip install -r requirements-dev.txt
python -m pip check
pytest -q
python -m playwright install --with-deps chromium
pytest -q tests/e2e
```

The dev requirements include `-c requirements.constraints.txt`. That generated
file copies only the runtime pins, without hashes, so pip can install unpinned
dev tools while being forbidden to upgrade runtime packages. It is not a second
production lock. On another OS, validate installation separately; use
`python -m playwright install chromium` on macOS.

`httpx2` is intentional: Starlette 1.2.1's `TestClient` imports it first. Its fallback
to `httpx` is deprecated. Application and Telegram code do not need this client.
E2E fixtures create their own local server/database and disable external services;
run tests from a disposable checkout when verifying dependency changes.

### Regeneration

The lock is produced from `requirements.txt`, not a working-venv `pip freeze`.
[uv supports explicit platform and Python resolution targets](https://docs.astral.sh/uv/concepts/resolution/#platform-specific-resolution).
Install the pinned resolver in its own environment:

```bash
python3.12 -m venv /tmp/student-assistant-lock-tools
source /tmp/student-assistant-lock-tools/bin/activate
python -m pip install uv==0.12.19
python scripts/compile_requirements.py
```

The script passes `--python-platform x86_64-unknown-linux-gnu`,
`--python-version 3.12`, `--generate-hashes`, and the existing production lock as
hard constraints. It also regenerates `requirements.constraints.txt`; commit or
review both files together. An incompatible requested version fails resolution
instead of upgrading the whole graph. For an intentional update, change only the
specific pin in the lock, regenerate, review the diff and repeat target checks.
Do not use a blanket `--upgrade` for routine regeneration.

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
- On Render, `RENDER_EXTERNAL_HOSTNAME` is detected automatically and added as an exact allowed host.
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

## Telegram: транспорт и отдельный scheduler

Для актуальных команд настройки, общей постоянной БД, перехода со старого webhook
и ограничений бесплатного Render используйте
[инструкцию Telegram](integrations/TELEGRAM_BOT_SETUP.md).
Web запускается текущим Docker CMD; scheduler — отдельным процессом
`python -m telegram_bot.scheduler`. Сборка образа не регистрирует webhook.

## Telegram production topology (hardening, 2026-10-03)

This is a prepared deployment plan, not a rollout. Use the same reviewed revision
and production image for both services. Do not run local polling with the live
production bot token.

| Render resource | Runtime / command | Database |
|---|---|---|
| `student-assistant-web` — Web Service | Main Dockerfile, default `python run.py`; bind `HOST=0.0.0.0`, Render supplies `PORT` | Internal connection string of `student-assistant-db` |
| `student-assistant-scheduler` — Background Worker | Same image, command override `python -m telegram_bot.scheduler` | The exact same database connection string |
| `student-assistant-db` — Render PostgreSQL | Persistent PostgreSQL; CI/local tests use PostgreSQL 16 | Shared by web and worker |

For a native Python deployment, both services must use Python 3.12 and the build
command `python -m pip install --require-hashes -r requirements.lock.txt` on Linux
x86_64. Start commands are the same as above. The Dockerfile already fixes Python
3.12 and checks hashes and dependencies. A missing migration is a fatal startup
error; PostgreSQL advisory transaction locking serializes simultaneous web/worker
migrations. Back up the database before applying any release.

Shared env names (set identical values through one Render environment group or
explicit references; never generate a different SECRET_KEY for each service):

`APP_ENV`, `DATABASE_URL`, `SECRET_KEY`, `COOKIE_SECURE`, `PUBLIC_ORIGIN`,
`ALLOWED_HOSTS`, `APP_TIMEZONE`, `TELEGRAM_MODE`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_WEBHOOK_PATH`,
`DISABLE_TELEGRAM`, `TESTING`, `PYTHON_DOTENV_DISABLED`.

Production uses `APP_ENV=production`, `TELEGRAM_MODE=webhook`, secure cookies,
Telegram enabled and testing disabled. `PUBLIC_ORIGIN` is the public HTTPS web
origin. Existing `PUBLIC_BASE_URL` is an alias; if both are supplied they must
match. The existing `TELEGRAM_USE_WEBHOOK` remains supported; do not supply a
conflicting value alongside `TELEGRAM_MODE`.

Web-specific names: `HOST`, `PORT`, `RELOAD` and optional SMTP configuration.
Worker-specific optional names: `TELEGRAM_DIGEST_CHECK_INTERVAL_SECONDS`,
`TELEGRAM_BOT_LOG_LEVEL`. The worker inherits the shared public/secret settings
because it imports the same validated application configuration and renders links.
Use the same direct PostgreSQL endpoint (or session pooling); do not use a
transaction pooler that breaks session/DDL assumptions without staging validation.

With Telegram enabled, production startup rejects SQLite and polling. A local
SQLite path cannot be shared between two Render services. Diagnostics expose a
safe database fingerprint: compare it in both services, then verify the same
workspace and worker heartbeat. A fingerprint is an operational check, not proof
of a healthy worker or a guarantee that two hosting URLs reach the same cluster.

`SECRET_KEY` must be persistent. It signs web sessions and participates in HMACs
for workspace/device/link/recovery credentials. Replacing it can invalidate access;
it must not be regenerated during ordinary deploys. Telegram dialog/callback state
uses DB records/random tokens, while Telegram link codes are short-lived DB values.
Production already rejects the random development key and insecure defaults.

Free web services sleep after 15 minutes without inbound traffic. Free compute
is not available for Background Workers, and Free PostgreSQL is not a persistent
production plan (its lifetime is limited). A sleeping web or absent worker cannot
provide timely reminders. Choose an always-on Background Worker, an external
scheduler with an always-on runtime, or another always-on deployment. A cron
invocation must call a **single** scheduler tick, not launch the endless worker
loop; its interval must fit notification grace windows (class reminders: 5 minutes).
No cron service or paid resource has been created by this change.
Sources: [Render Free](https://render.com/docs/free),
[Background Workers](https://render.com/docs/background-workers),
[environment references](https://render.com/docs/blueprint-spec).

Before approving merge/deploy, require the new `Telegram + PostgreSQL / Python
3.12` CI job and the existing full Linux CI. The new job installs the hashed lock,
runs migrations and all Telegram/scheduler/concurrency/HTTP-smoke tests on a
PostgreSQL service, runs Telegram browser E2E with isolated SQLite browser DBs,
and checks the actual Docker image both with the default web command and the
scheduler command override. No real Telegram secrets are used.

Local evidence, release gates, troubleshooting and the manual live checklist:
[Telegram verification](integrations/TELEGRAM_VERIFICATION.md).

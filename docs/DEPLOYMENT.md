# Production Deployment

## Goal

Use PostgreSQL in production so accounts and data are not lost after server restarts or redeploys.

## Dependency installation and lock regeneration

### Local development

Use a local virtual environment and `python -m pip install -r requirements.txt`.
This file declares direct application dependencies, including the existing password
and email validation libraries. Test tooling is declared in `requirements-dev.txt`.
Do not update an existing working environment merely to regenerate the lock.

### Production candidate

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

Validation so far: clean installation, imports, real SVG QR generation and an HTTP
startup with temporary SQLite succeeded on **macOS arm64 / CPython 3.12.14**.
All Linux x86_64 / CPython 3.12 wheels were downloaded with hash verification.
This is a cross-platform resolution and wheel check, **not a Linux execution test**.
Docker/Podman and a Linux runtime were unavailable during this change.
The Dockerfile therefore still installs `requirements.txt`. Before switching it,
verify installation, `pip check`, QR SVG, isolated startup, tests and E2E inside
Linux/Python 3.12, then build and run the resulting Docker image.
No existing Render service configuration needs to be changed for this stage.

Recorded verification (macOS arm64 / CPython 3.12.14): production and dev
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

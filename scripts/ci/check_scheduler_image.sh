#!/usr/bin/env bash
# A real process using the production image, fake token and an empty isolated DB.
set -euo pipefail
image=${1:?Image required}
container_name=${2:?Container name required}
trap 'docker rm -f "$container_name" >/dev/null 2>&1 || true' EXIT
# Tests populated the CI database; reset only its allowlisted test schema first.
python - <<'PY'
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
url=make_url(os.environ['TELEGRAM_TEST_DATABASE_URL'])
assert url.database == 'sa_telegram_test_ci'
engine=create_engine(url)
with engine.begin() as connection:
    connection.execute(text('DROP SCHEMA public CASCADE'))
    connection.execute(text('CREATE SCHEMA public'))
engine.dispose()
PY
docker run -d --name "$container_name" --network host \
  -e PYTHON_DOTENV_DISABLED=1 -e APP_ENV=production -e COOKIE_SECURE=true \
  -e DATABASE_URL="${TELEGRAM_TEST_DATABASE_URL}" \
  -e SECRET_KEY=telegram-image-ci-only-persistent-secret-key \
  -e PUBLIC_ORIGIN=https://example.invalid -e ALLOWED_HOSTS=example.invalid \
  -e TELEGRAM_MODE=webhook -e TELEGRAM_BOT_TOKEN=ci-fake-token \
  -e TELEGRAM_BOT_USERNAME=ci_fake_bot \
  -e TELEGRAM_WEBHOOK_SECRET=telegram-image-ci-only-hook-secret-key \
  "$image" python -m telegram_bot.scheduler >/dev/null
python - <<'PY'
import os,time
from sqlalchemy import create_engine,text
engine=create_engine(os.environ['TELEGRAM_TEST_DATABASE_URL'])
for _ in range(60):
    try:
        with engine.connect() as connection:
            data=connection.execute(text("SELECT data FROM telegram_state WHERE key='scheduler-heartbeat'")).scalar()
        if data and data['state']=='completed':
            print('PASS: scheduler production process, shared PostgreSQL, completed heartbeat')
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit('Scheduler heartbeat missing')
engine.dispose()
PY
docker stop --time 30 "$container_name" >/dev/null
test "$(docker inspect --format '{{.State.ExitCode}}' "$container_name")" = 0
printf '%s\n' 'PASS: graceful scheduler shutdown'

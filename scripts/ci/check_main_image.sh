#!/usr/bin/env bash
# Check the actual production image and its default CMD, never a copied app.
set -euo pipefail

image=${1:?Usage: bash scripts/ci/check_main_image.sh IMAGE CONTAINER_NAME}
container_name=${2:?Provide a unique container name}
container_id=''
umask 077
work=$(mktemp -d)
cleanup() {
  if [[ -n "$container_id" ]]; then
    docker rm --force "$container_id" >/dev/null 2>&1 || true
  fi
  rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

test "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")" = linux/amd64
test "$(docker image inspect --format '{{json .Config.Cmd}}' "$image")" = '["python","run.py"]'
test "$(docker image inspect --format '{{json .Config.Entrypoint}}' "$image")" = null

# Explicit test settings only: never source .env or forward the host environment.
cat > "$work/test.env" <<'ENV'
APP_ENV=test
TESTING=true
SECRET_KEY=student-assistant-main-image-ci-only-test-key
DATABASE_URL=sqlite:////tmp/student-assistant-ci.db
PYTHON_DOTENV_DISABLED=1
HOST=0.0.0.0
PORT=8000
RELOAD=false
COOKIE_SECURE=false
ALLOWED_HOSTS=127.0.0.1,localhost
PUBLIC_BASE_URL=http://127.0.0.1
ALLOW_LOCAL_PRIVATE_DATA=false
DISABLE_TELEGRAM=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_API_TOKEN=
TELEGRAM_BOT_API_BASE_URL=
TELEGRAM_USE_WEBHOOK=false
TELEGRAM_WEBHOOK_BASE_URL=
TELEGRAM_WEBHOOK_SECRET=
SMTP_HOST=
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
ENV

# No command/entrypoint override. The database lives only in the container tmpfs.
container_id=$(docker create --name "$container_name" --platform linux/amd64 \
  --read-only --tmpfs /tmp:rw,nosuid,size=256m \
  --publish 127.0.0.1::8000 --env-file "$work/test.env" "$image")
docker start "$container_id" >/dev/null
docker exec "$container_id" python -m pip check
docker exec "$container_id" python scripts/ci/check_runtime.py --production-only
docker exec -i "$container_id" python - <<'PY'
from pathlib import Path
import platform
import sys

assert (platform.system(), platform.machine(), sys.version_info[:2]) == ('Linux', 'x86_64', (3, 12))
for path in Path('/app').rglob('*'):
    name = path.name
    forbidden = (
        name in {'.git', '.env', 'venv', '.venv', 'data', 'test-results', 'playwright-report'}
        or (name.startswith('.env.') and name != '.env.example')
        or name.endswith(('.db', '.sqlite', '.sqlite3'))
        or any(marker in name for marker in ('.db-', '.sqlite-', '.sqlite3-'))
    )
    if forbidden:
        raise SystemExit('Unexpected local state in application image (contents not logged)')
print('PASS: target platform and image excludes local state')
from scripts.ci.smoke_runtime import IMPORT_PROBE
exec(IMPORT_PROBE)
PY

address=$(docker port "$container_id" 8000/tcp)
[[ "$address" =~ ^127\.0\.0\.1:[0-9]+$ ]]
deadline=$((SECONDS + 45))
while (( SECONDS < deadline )); do
  if [[ "$(docker inspect --format '{{.State.Running}}' "$container_id")" != true ]]; then
    echo 'Application container exited before HTTP readiness' >&2
    exit 1
  fi
  # Discard body and headers: no CSRF tokens, keys or cookies in diagnostics.
  status=$(curl --noproxy '*' --silent --output /dev/null --write-out '%{http_code}' \
    --max-time 2 "http://$address/login") || status=000
  if [[ "$status" == 200 ]]; then
    echo 'PASS: default CMD python run.py, published loopback port, HTTP /login 200'
    exit 0
  fi
  sleep 1
done
echo 'HTTP readiness timed out after 45 seconds' >&2
exit 1

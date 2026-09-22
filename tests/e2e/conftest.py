from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIRECTORY = PROJECT_ROOT / 'test-results' / 'e2e'


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def _wait_for_server(url: str, process: subprocess.Popen, log_path: Path) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_text = log_path.read_text(encoding='utf-8', errors='replace')
            pytest.fail(f'E2E server stopped during startup.\n{log_text}')
        try:
            with urlopen(f'{url}/login', timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.15)

    process.terminate()
    pytest.fail(f'E2E server did not become ready at {url} within 30 seconds.')


def _stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            check=False,
            capture_output=True,
            text=True,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _unlink_with_retry(path: Path) -> None:
    for attempt in range(20):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.1)


@pytest.fixture(scope='session')
def e2e_runtime(tmp_path_factory):
    runtime_directory = tmp_path_factory.mktemp('student-assistant-e2e')
    database_path = runtime_directory / 'test_e2e.db'
    server_log_path = runtime_directory / 'server.log'
    port = _available_port()
    base_url = f'http://127.0.0.1:{port}'

    environment = os.environ.copy()
    environment.update(
        {
            'APP_ENV': 'test',
            'TESTING': 'true',
            'SECRET_KEY': 'student-assistant-e2e-secret-key-only-for-local-tests',
            'COOKIE_SECURE': 'false',
            'DATABASE_URL': f'sqlite:///{database_path.as_posix()}',
            'HOST': '127.0.0.1',
            'PORT': str(port),
            'RELOAD': 'false',
            'ALLOWED_HOSTS': '127.0.0.1,localhost',
            'PUBLIC_BASE_URL': base_url,
            'ALLOW_LOCAL_PRIVATE_DATA': 'false',
            'DISABLE_TELEGRAM': 'true',
            'TELEGRAM_BOT_TOKEN': '',
            'TELEGRAM_BOT_API_TOKEN': '',
            'TELEGRAM_USE_WEBHOOK': 'false',
            'TELEGRAM_WEBHOOK_BASE_URL': '',
            'TELEGRAM_WEBHOOK_SECRET': '',
            'SMTP_HOST': '',
            'SMTP_USERNAME': '',
            'SMTP_PASSWORD': '',
            'SMTP_FROM_EMAIL': '',
            'PYTHONUNBUFFERED': '1',
        }
    )

    with server_log_path.open('w+', encoding='utf-8') as server_log:
        process = subprocess.Popen(
            [
                sys.executable,
                '-m',
                'uvicorn',
                'app.main:app',
                '--host',
                '127.0.0.1',
                '--port',
                str(port),
                '--log-level',
                'warning',
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _wait_for_server(base_url, process, server_log_path)

        try:
            yield {
                'base_url': base_url,
                'database_path': database_path,
                'server_log_path': server_log_path,
            }
        finally:
            _stop_server(process)
            for database_file in (
                database_path,
                Path(f'{database_path}-shm'),
                Path(f'{database_path}-wal'),
            ):
                _unlink_with_retry(database_file)


@pytest.fixture(scope='session')
def base_url(e2e_runtime) -> str:
    return e2e_runtime['base_url']


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f'rep_{report.when}', report)


@pytest.fixture
def e2e_page(browser, base_url, request):
    context = browser.new_context(
        base_url=base_url,
        viewport={'width': 1440, 'height': 1000},
        service_workers='block',
    )
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()

    yield page

    failed = bool(getattr(request.node, 'rep_call', None) and request.node.rep_call.failed)
    if failed:
        ARTIFACTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r'[^a-zA-Z0-9_.-]+', '-', request.node.nodeid).strip('-')
        page.screenshot(
            path=ARTIFACTS_DIRECTORY / f'{safe_name}.png',
            full_page=True,
        )
        context.tracing.stop(path=ARTIFACTS_DIRECTORY / f'{safe_name}.zip')
    else:
        context.tracing.stop()
    context.close()

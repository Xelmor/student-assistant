"""Isolated production-mode web + two workers. No Telegram network or real secrets."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, ProxyHandler

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def main():
    target = os.environ['TELEGRAM_PROCESS_TEST_DATABASE_URL']
    url = make_url(target)
    if url.get_backend_name() != 'postgresql' or not (url.database or '').startswith('sa_telegram_test_'):
        raise SystemExit('An isolated sa_telegram_test_* PostgreSQL database is required')
    engine = create_engine(url, hide_parameters=True)
    if inspect(engine).get_table_names():
        raise SystemExit('Process smoke requires a clean database')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    env = os.environ.copy()
    env.update(PYTHON_DOTENV_DISABLED='1', APP_ENV='production', TESTING='false', DISABLE_TELEGRAM='false',
               DATABASE_URL=target, SECRET_KEY='process-smoke-ci-only-persistent-secret-key', COOKIE_SECURE='true',
               PUBLIC_ORIGIN='https://example.invalid', PUBLIC_BASE_URL='https://example.invalid',
               ALLOWED_HOSTS='127.0.0.1,example.invalid', HOST='127.0.0.1', PORT=str(port), RELOAD='false',
               TELEGRAM_MODE='webhook', TELEGRAM_USE_WEBHOOK='true', TELEGRAM_BOT_TOKEN='fake-process-smoke',
               TELEGRAM_BOT_API_TOKEN='', TELEGRAM_BOT_USERNAME='fake_process_bot',
               TELEGRAM_WEBHOOK_SECRET='process-smoke-ci-only-persistent-hook-secret',
               TELEGRAM_WEBHOOK_BASE_URL='', TELEGRAM_BOT_API_BASE_URL='', SMTP_HOST='',
               TELEGRAM_DIGEST_CHECK_INTERVAL_SECONDS='10')
    processes=[]
    with tempfile.TemporaryDirectory(prefix='sa-process-smoke-') as directory:
        try:
            for index, command in enumerate([['run.py'], ['-m','telegram_bot.scheduler'], ['-m','telegram_bot.scheduler']]):
                with (Path(directory)/f'{index}.log').open('w') as output:
                    processes.append(subprocess.Popen([sys.executable,*command],env=env,stdout=output,stderr=subprocess.STDOUT))
            opener=build_opener(ProxyHandler({}))
            for _ in range(100):
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError('Production process exited during startup (logs withheld)')
                try:
                    with engine.connect() as connection:
                        row=connection.execute(text("SELECT data FROM telegram_state WHERE key='scheduler-heartbeat'")).scalar()
                    with opener.open(f'http://127.0.0.1:{port}/login',timeout=1) as response:
                        ready=response.status == 200
                    if row and row['state']=='completed' and ready and all('scheduler started' in (Path(directory)/f'{i}.log').read_text() for i in (1,2)):
                        print('PASS: production web HTTP 200, clean PostgreSQL migrations, two worker processes and heartbeat')
                        break
                except Exception:
                    pass
                time.sleep(.2)
            else:
                raise RuntimeError('Production process smoke timed out')
            previous = row['completed_at']
            # Terminate only sessions in this isolated smoke DB, never other DBs.
            with engine.begin() as connection:
                connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid() AND backend_type='client backend'"), {'name':url.database})
            for _ in range(150):
                with engine.connect() as connection:
                    current=connection.execute(text("SELECT data FROM telegram_state WHERE key='scheduler-heartbeat'")).scalar()
                if current and current.get('completed_at') != previous and current['state']=='completed':
                    print('PASS: workers recover after PostgreSQL connections are terminated')
                    break
                time.sleep(.2)
            else:
                raise RuntimeError('Worker did not reconnect')
        finally:
            for process in processes:
                if process.poll() is None: process.send_signal(signal.SIGTERM)
            for process in processes:
                try: process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(); raise RuntimeError('Graceful shutdown timed out')
            engine.dispose()
        # Uvicorn re-raises SIGTERM after its graceful shutdown; workers return 0.
        assert processes[0].returncode in (0, -signal.SIGTERM), 'Web exit was not SIGTERM/clean'
        assert 'Application shutdown complete.' in (Path(directory)/'0.log').read_text(), 'Web did not finish shutdown'
        assert all(p.returncode == 0 for p in processes[1:]), 'Worker exit was not clean'
        print('PASS: web and both workers exit cleanly on SIGTERM')


if __name__ == '__main__': main()

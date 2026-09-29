"""Exercise production imports, QR SVG and HTTP using a disposable application copy."""
import argparse
import os
from pathlib import Path
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, ProxyHandler


ROOT = Path(__file__).resolve().parents[2]
IMPORT_PROBE = '''
import base64
import xml.etree.ElementTree as ET
import app.main
import telegram_bot.polling
import telegram_bot.scheduler
import bcrypt, email_validator, pwdlib, psycopg
from app.services.workspace_sync import qr_svg_data_uri
uri = qr_svg_data_uri('https://example.invalid/ci-qr')
assert uri.startswith('data:image/svg+xml;base64,')
svg = ET.fromstring(base64.b64decode(uri.split(',', 1)[1], validate=True))
assert svg.tag == '{http://www.w3.org/2000/svg}svg'
assert svg.find('{http://www.w3.org/2000/svg}path') is not None
print('PASS: application/Telegram imports and real QR SVG generation', flush=True)
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-target', action='store_true')
    args = parser.parse_args()
    target = (platform.system(), platform.machine(), sys.version_info[:2])
    print(f'Runtime: {target}; Python {platform.python_version()}', flush=True)
    if args.require_target and target != ('Linux', 'x86_64', (3, 12)):
        raise SystemExit('This check requires Linux x86_64 / Python 3.12')

    with tempfile.TemporaryDirectory(prefix='sa-ci-smoke-') as directory:
        work = Path(directory)
        for name in ('app', 'telegram_bot'):
            shutil.copytree(ROOT / name, work / name, ignore=shutil.ignore_patterns(
                '__pycache__', '*.pyc', '.env', '.env.*', '*.db', '*.sqlite*', 'data'))
        shutil.copy2(ROOT / 'run.py', work / 'run.py')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = os.environ.copy()
        env.update({
            'APP_ENV': 'test', 'TESTING': 'true', 'SECRET_KEY': secrets.token_urlsafe(48),
            'DATABASE_URL': f'sqlite:///{work / "smoke.db"}',
            'PYTHON_DOTENV_DISABLED': '1', 'PYTHONPATH': str(work),
            'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1',
            'HOST': '127.0.0.1', 'PORT': str(port), 'RELOAD': 'false',
            'COOKIE_SECURE': 'false', 'ALLOWED_HOSTS': '127.0.0.1,localhost,testserver',
            'PUBLIC_BASE_URL': f'http://127.0.0.1:{port}', 'ALLOW_LOCAL_PRIVATE_DATA': 'false',
            'DISABLE_TELEGRAM': 'true', 'TELEGRAM_BOT_TOKEN': '', 'TELEGRAM_BOT_API_TOKEN': '',
            'TELEGRAM_USE_WEBHOOK': 'false', 'TELEGRAM_WEBHOOK_BASE_URL': '',
            'TELEGRAM_WEBHOOK_SECRET': '', 'TELEGRAM_BOT_API_BASE_URL': '',
            'SMTP_HOST': '', 'SMTP_USERNAME': '', 'SMTP_PASSWORD': '', 'SMTP_FROM_EMAIL': '',
        })
        subprocess.run([sys.executable, '-c', IMPORT_PROBE], cwd=work, env=env,
                       check=True, timeout=45)
        log_path = work / 'server.log'
        with log_path.open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, 'run.py'], cwd=work, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                opener = build_opener(ProxyHandler({}))  # Local smoke must not use a proxy.
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError('Application exited during startup')
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/login', timeout=1) as response:
                            if response.status != 200 or b'<html' not in response.read().lower():
                                raise RuntimeError('Expected HTTP 200 and an HTML page')
                            print('PASS: temporary SQLite, run.py startup, HTTP /login 200', flush=True)
                            break
                    except OSError:
                        time.sleep(0.2)
                else:
                    raise RuntimeError('Application startup timed out')
            except Exception:
                print(log_path.read_text(encoding='utf-8'), file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == '__main__':
    main()

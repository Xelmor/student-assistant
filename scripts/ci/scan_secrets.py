"""Offline repository/history secret heuristics. Never prints matched values."""
import re
import argparse
import subprocess
from pathlib import Path

PATTERNS = {
    'telegram_token': re.compile(r'\b\d{7,12}:[A-Za-z0-9_-]{30,}\b'),
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'database_password': re.compile(r'postgres(?:ql)?(?:\+psycopg)?://[^\s/:]+:([^\s/@]+)@'),
    'assigned_secret': re.compile(r'''(?:SECRET_KEY|TELEGRAM_WEBHOOK_SECRET)\s*[=:]\s*["']?([A-Za-z0-9_/-]{32,})'''),
}
PLACEHOLDERS = ('test', 'example', 'placeholder', 'change', 'replace', 'your-', 'your_', 'ci-only', '<', '${')


def scan(content):
    found = set()
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(content):
            value = match.group(1) if match.lastindex else match.group(0)
            if any(marker in value.lower() for marker in PLACEHOLDERS):
                continue
            if name == 'database_password' and value.lower() in {'password','postgres','user','pass'}:
                continue  # Explicit illustrative/local CI credentials only.
            found.add(name)
    return sorted(found)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true')
    args=parser.parse_args()
    paths = subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard']).decode().split('\0')
    failures = []
    for name in set(filter(None,paths)):
        path = Path(name)
        if path.is_file():
            failures.extend((name, rule) for rule in scan(path.read_text(errors='replace')))
        if name == '.env' or name.endswith('/.env'):
            failures.append((name,'tracked_env'))
    if args.history:
        try:
            history = subprocess.check_output(['git','log','--all','--format=','--patch','--no-ext-diff','--no-textconv','--no-renames','--diff-algorithm=histogram'],timeout=60).decode(errors='replace')
            failures.extend(('git_history',rule) for rule in scan(history))
        except subprocess.TimeoutExpired:
            failures.append(('git_history','history_scan_timed_out'))
    for name,rule in sorted(set(failures)):
        print(f'FAIL {rule}: {name} (value withheld)')
    print(f'Secret scan: {len(set(failures))} findings; working tree checked; history checked only with --history; heuristic, not a guarantee.')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())

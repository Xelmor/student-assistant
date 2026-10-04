"""Offline secret scan of working tree, HEAD, and optionally all reachable history.

Read each distinct Git blob once, without diffs, checkout, network, or secret output.
Exit 0 = PASS, 1 = findings, 2 = incomplete/error (never a false clean result).
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


@dataclass(frozen=True)
class Hit:
    kind: str
    fingerprint: str


def fingerprint(value):
    return 'sha256:' + hashlib.sha256(value.encode('utf-8', errors='replace')).hexdigest()[:16]


PROVIDERS = {
    'telegram_bot_token': re.compile(r'(?<![\w])\d{5,12}:[A-Za-z0-9_-]{30,}(?![\w-])'),
    'github_api_key': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b'),
    'aws_access_key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'google_api_key': re.compile(r'\bAIza[A-Za-z0-9_-]{35}\b'),
    'api_key': re.compile(r'\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|[rs]k_live_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{20,})\b'),
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'),
}
PRIVATE_HEADER = re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----')
DB_URL = re.compile(r'(?i)\b(?:postgres(?:ql)?(?:\+\w+)?|mysql(?:\+\w+)?|mariadb|mongodb(?:\+srv)?|redis|rediss|mssql(?:\+\w+)?)://[^\s/:@]+:([^\s/@"\'<>]+)@')
VALUE = r'''("[^"\r\n]*"|'[^'\r\n]*'|[^\s,;\}\)\]]+)'''
ASSIGN = re.compile(r'''(?i)(?<![\w.-])([a-z_][a-z0-9_]{0,100})["']?[ \t]*(?:=|:)[ \t]*''' + VALUE)
ENV_DEFAULT = re.compile(r'''(?i)(?:getenv|environ\.get)\(\s*["']([a-z_][a-z0-9_]*)["']\s*,\s*''' + VALUE)
YAML_VALUE = re.compile(r'''(?im)^\s*-?\s*(?:key|name):\s*([A-Z_][A-Z0-9_]*)\s*\n\s+value:\s*''' + VALUE)
# Whole-value, recognisable examples. Never ignore arbitrary secrets containing "test".
PLACEHOLDER = re.compile(r'(?i)^(?:<[^>]+>|\$.*|\{\{.*|\{[a-z_][\w.()]*\}|(?:your|replace|change|example|placeholder)[_-].*|change_?me|x{3,}|\*{3,})$')
SYNTHETIC = re.compile(r'(?i)^(?:(?:test|fake|dummy|isolated|ci|dev)[_-].*|[a-z0-9_-]*-ci-only-[a-z0-9_-]+)$')
TEST_VALUES = {'secret', 'private', 'token', 'password', 'password123', 'password123!',
               'pass', 'fake', 'test', 'old', 'new', 'correct', 'wrong', 'valid', 'invalid',
               'old-secret', 'new-secret', 'new-password', 'password456'}
ENV_TEMPLATES = {'.env.example', '.env.sample', '.env.template', '.env.dist'}
PRUNE = {'.git', 'venv', '.venv', 'node_modules', '__pycache__', '.pytest_cache', 'test-results'}
# Reviewed literals used only in isolated tests or documentation. Exact path,
# type and fingerprint: a different value/path still fails, even under tests/.
# No production credentials belong in this allowlist.
REVIEWED_EXAMPLES = {
    # Invalid short password input and reset-form fixture.
    ('tests/test_account_normalization.py', 'password', 'sha256:a665a45920422f9d'),
    ('tests/test_password_hint.py', 'password', 'sha256:fb3e284bdf675c5c'),
    # Invalid-short/long-enough configuration examples; disabled-delivery sentinel.
    ('tests/test_config.py', 'secret_key', 'sha256:f9b0078b5df596d2'),
    ('tests/test_config.py', 'secret_key', 'sha256:cb3bc3c397fea3a8'),
    ('tests/test_config.py', 'password', 'sha256:3c3f9dd15a1a1432'),
    ('tests/test_config.py', 'telegram_bot_token', 'sha256:3c3f9dd15a1a1432'),
    # Local isolated browser server and disposable registration account.
    ('tests/e2e/conftest.py', 'secret_key', 'sha256:0ee16a62d38f8899'),
    ('tests/e2e/test_auth.py', 'password', 'sha256:ffc121a2210958bf'),
    # Fake HTTP webhook headers in browser fixtures; never Telegram delivery.
    ('tests/e2e/test_telegram_evening_digest.py', 'webhook_secret', 'sha256:8848896ed493d69e'),
    ('tests/e2e/test_telegram_search.py', 'webhook_secret', 'sha256:1ff6109d4f0c49af'),
    ('tests/e2e/test_telegram_weekly_digest.py', 'webhook_secret', 'sha256:9307cff4d98a982d'),
    # Historical Russian instruction to paste a BotFather token, not a token.
    ('README.md', 'telegram_bot_token', 'sha256:3be4a94b3f2d7020'),
    # Historical development-only fallback: get_settings raises in production
    # before choosing this value. app/main.py is handled separately below,
    # only for its reviewed historical commits, never in working tree/HEAD.
    ('app/core/config.py', 'secret_key', 'sha256:7e0feefa9129e367'),
}


# Reviewed 2026-10-04: development fallback, not a production credential.
# Keep the finding visible. Do not add this to scan() / REVIEWED_EXAMPLES:
# reintroducing it in HEAD, the working tree or another commit must still fail.
KNOWN_SAFE_HISTORY = {
    ('app/main.py', 'secret_key', 'sha256:376912d192756c41'): frozenset({
        '969bb1548ef65fefd2de118c3e67e508f86b8240',
        '3fad685827252c964f419a993bddbd90694396fd',
        '3a7b6efe83aba3044033cc93b1bb0a8644d7acb6',
        '06c60e7a4512eccccc03c1d6c0e168815b49bedb',
        '35c7ed89a15d5282c5caa41775e845692a122b8a',
        '5f0773611be268d191dc2b08061c0d305f8b10c0',
        'a98e9bdc25f98889930c94ffc7f59f0614d6cba8',
        '0e2445521d5cc1002ea5f9e57e8917bd25dcee01',
    }),
}


def history_allowlisted(commit, path, hit):
    return commit in KNOWN_SAFE_HISTORY.get((path, hit.kind, hit.fingerprint), ())


def secret_kind(key):
    key = key.lower().replace('-', '_').replace('.', '_')
    if key.endswith(('_hash', '_hashes')) or any(word in key for word in ('configured', 'matches', 'ttl', 'seconds', 'expires', 'length')):
        return None
    if key in {'secret_key', 'development_secret_key'}:
        return 'secret_key'
    if 'telegram' in key and 'token' in key:
        return 'telegram_bot_token'
    if 'webhook' in key and ('secret' in key or 'token' in key):
        return 'webhook_secret'
    if ('recovery' in key or 'device' in key) and ('token' in key or 'key' in key):
        return 'recovery_device_token'
    if key in {'password', 'passwd', 'pwd', 'password_confirm', 'password_confirmation'} or key.endswith(('_password', '_passwd', '_pwd')):
        return 'password'
    if any(word in key for word in ('api_key', 'apikey', 'access_key', 'client_secret', 'auth_token', 'access_token', 'refresh_token', 'private_key')):
        return 'api_key'
    if key in {'token', 'secret', 'raw_token', 'recovery_key'}:
        return 'generic_token'
    return None


def example_value(value, path, *, provider=False):
    if not value or PLACEHOLDER.fullmatch(value):
        return True
    if provider:
        # Recognisable repeated dummy payloads, never a generic substring allowlist.
        body = value.split(':', 1)[-1]
        return len(set(body)) <= 2 and len(body) >= 20
    parts = Path(path).parts
    illustrative = ('tests' in parts or 'docs' in parts or Path(path).name in ENV_TEMPLATES
                    or Path(path).suffix == '.md' or '.github' in parts or path.startswith('scripts/ci/'))
    return illustrative and (value.lower() in TEST_VALUES or bool(SYNTHETIC.fullmatch(value)))


def scan(content: bytes, path: str) -> tuple[Hit, ...]:
    # Scan binary blobs too: ASCII secrets embedded in them remain visible.
    text = content.decode('utf-8', errors='replace')
    if content.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = content.decode('utf-16', errors='replace')
    hits = set()
    for kind, pattern in PROVIDERS.items():
        for match in pattern.finditer(text):
            value = match.group()
            if not example_value(value, path, provider=True):
                hits.add(Hit(kind, fingerprint(value)))
    if PRIVATE_HEADER.search(text) and not PROVIDERS['private_key'].search(text):
        # A truncated key is still suspicious, but literal detector code is not a key.
        for line in text.splitlines():
            if PRIVATE_HEADER.fullmatch(line.strip()):
                hits.add(Hit('private_key', fingerprint(line.strip())))
    for match in DB_URL.finditer(text):
        password = match[1]
        if not example_value(password, path):
            hits.add(Hit('database_credentials', fingerprint(password)))
    env_file = Path(path).name.startswith('.env')
    for pattern in (ASSIGN, ENV_DEFAULT, YAML_VALUE):
        for match in pattern.finditer(text):
            key, raw = match[1], match[2]
            kind = secret_kind(key)
            if not kind:
                continue
            quoted = raw.startswith(('"', "'"))
            value = raw[1:-1] if quoted else raw
            source_file = Path(path).suffix in {'.py', '.js', '.ts', '.tsx', '.jsx'}
            if not quoted and not env_file and source_file and (re.fullmatch(r'[A-Za-z_][\w.]*', value) or any(c in value for c in '([{')):
                continue  # Variable reference, type, function call, not a literal.
            if not quoted and value in {'None', 'null', 'true', 'false', 'True', 'False'} and not env_file:
                continue
            if example_value(value, path):
                continue
            hits.add(Hit(kind, fingerprint(value)))
    hits = {h for h in hits if (path, h.kind, h.fingerprint) not in REVIEWED_EXAMPLES}
    return tuple(sorted(hits, key=lambda h: (h.kind, h.fingerprint)))


class ScanError(Exception):
    pass


class Git:
    def __init__(self, root, timeout):
        self.root = Path(root)
        self.deadline = time.monotonic() + timeout
        self.env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1',
                    'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0'}

    def remaining(self):
        seconds = self.deadline - time.monotonic()
        if seconds <= 0:
            raise ScanError('scan_timeout; scan incomplete')
        return seconds

    def run(self, *args):
        try:
            return subprocess.check_output(['git', '-C', str(self.root), *args], env=self.env,
                                           stderr=subprocess.PIPE, timeout=self.remaining())
        except subprocess.TimeoutExpired:
            raise ScanError('git_read_timeout; make cloud placeholders available locally before retrying') from None
        except subprocess.CalledProcessError:
            raise ScanError('git_read_failed; missing/unavailable objects or invalid repository') from None

    def blobs(self, oids):
        yield from self.objects(oids, 'blob')

    def objects(self, oids, expected_kind):
        # Temporary files contain ONLY object IDs and blob data; live solely inside
        # a private TemporaryDirectory and are removed even on timeout/errors.
        # File-backed stdout avoids pipe deadlock when a large blob fills the pipe.
        with tempfile.TemporaryDirectory(prefix='sa-secret-scan-') as directory:
            requests = Path(directory) / 'ids'
            output = Path(directory) / 'objects'
            requests.write_bytes(b''.join(oid.encode() + b'\n' for oid in oids))
            try:
                with requests.open('rb') as source, output.open('w+b') as sink:
                    subprocess.run(['git', '-C', str(self.root), 'cat-file', '--batch'], env=self.env,
                                   stdin=source, stdout=sink, stderr=subprocess.PIPE,
                                   timeout=self.remaining(), check=True)
                    sink.seek(0)
                    for expected in oids:
                        self.remaining()
                        header = sink.readline().split()
                        if len(header) != 3 or header[0].decode() != expected or header[1].decode() != expected_kind:
                            raise ScanError('missing_or_invalid_object')
                        size = int(header[2])
                        data = sink.read(size)
                        if len(data) != size or sink.read(1) != b'\n':
                            raise ScanError('incomplete_object_read')
                        yield expected, data
            except subprocess.TimeoutExpired:
                raise ScanError('git_object_timeout; make cloud placeholders available locally before retrying') from None
            except subprocess.CalledProcessError:
                raise ScanError('git_object_read_failed') from None


def tree(git, commit):
    entries = []
    for row in git.run('ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
        if not row:
            continue
        meta, path = row.split(b'\t', 1)
        mode, kind, oid = meta.split()
        if kind == b'commit':
            raise ScanError('submodule_history_requires_separate_scan')
        if kind == b'blob':
            entries.append((path.decode('utf-8', errors='surrogateescape'), oid.decode()))
    return entries


def working_files(git):
    names = set(filter(None, git.run('ls-files', '-z', '--cached', '--others', '--exclude-standard').decode('utf-8', errors='surrogateescape').split('\0')))
    # Also inspect ignored local files (including .env, keys and databases),
    # except dependency/generated-cache directories. Never follow directory links.
    for directory, dirs, files in os.walk(git.root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in PRUNE and not Path(directory, d).is_symlink()]
        for name in files:
            if name != '.git':
                names.add(Path(directory, name).relative_to(git.root).as_posix())
    return sorted(names)


def scope_report():
    return {'status': 'PASS', 'commits': 0, 'files': 0, 'unique_blobs': 0,
            'env_files': 0, 'findings': [], 'allowlisted': [], 'seconds': 0.0}


def audit(root, *, history=False, timeout=120):
    start = time.monotonic()
    git = Git(root, timeout)
    report = {'scanner': 'deterministic-local-v2', 'scopes': {}, 'limitations': [
        'Heuristic detection; no online credential validation.',
        'Reachable local refs and HEAD only, including tree/blob refs and commit/tag metadata; no reflogs, unreachable objects, remote-only refs or external LFS content.',
        'Working tree includes ignored files outside dependency/cache directories; tracked files are never pruned.',
    ]}
    scopes = report['scopes']
    scopes['working_tree'] = scope_report()
    scopes['head'] = scope_report()
    if history:
        scopes['history'] = scope_report()
    current_scope = 'working_tree'
    try:
        head = git.run('rev-parse', '--verify', 'HEAD').decode().strip()
        tracked = set(filter(None, git.run('ls-files', '-z', '--cached').decode('utf-8', errors='surrogateescape').split('\0')))
        began = time.monotonic()
        for name in working_files(git):
            git.remaining()
            path = git.root / name
            if not path.exists() and not path.is_symlink():
                continue  # Tracked deletion is still covered by HEAD/history.
            if getattr(path.lstat(), 'st_flags', 0) & 0x40000000:
                raise ScanError('cloud_placeholder; download working files before retrying')
            # Do not follow symlinks out of the repository.
            data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
            scope = scopes['working_tree']
            scope['files'] += 1
            scope['env_files'] += int(Path(name).name.startswith('.env'))
            for hit in scan(data, name):
                scope['findings'].append({'commit': None, 'path': name, 'tracked': name in tracked, **asdict(hit)})
        scopes['working_tree']['seconds'] = round(time.monotonic() - began, 3)
        current_scope = 'head'
        began = time.monotonic()
        snapshots = {head: tree(git, head)}
        scopes['head']['commits'] = 1
        metadata_findings = []
        extra_roots = set()
        metadata_objects = 0
        if history:
            current_scope = 'history'
            if git.run('rev-parse', '--is-shallow-repository').strip() == b'true':
                raise ScanError('shallow_history; CI requires checkout fetch-depth: 0')
            commits = git.run('rev-list', '--all', 'HEAD').decode().splitlines()
            for commit in commits:
                if commit not in snapshots:
                    snapshots[commit] = tree(git, commit)
            scopes['history']['commits'] = len(commits)
            for oid, data in git.objects(commits, 'commit'):
                metadata_objects += 1
                metadata_findings.extend({'commit': oid, 'path': '<commit metadata>',
                                          **asdict(hit), 'commits': [oid]}
                                         for hit in scan(data, '<commit metadata>'))
            # --all can contain non-commit refs (e.g. tooling snapshots). Include
            # those trees/blobs too, and peel annotated tags without discarding
            # tag messages. Ref names are not needed in logs.
            pending = [tuple(row.split()) for row in git.run(
                'for-each-ref', '--format=%(objecttype) %(objectname)').decode().splitlines()]
            seen = set()
            while pending:
                kind, oid = pending.pop()
                if oid in seen:
                    continue
                seen.add(oid)
                if kind == 'tag':
                    _, data = next(git.objects([oid], 'tag'))
                    metadata_objects += 1
                    metadata_findings.extend({'commit': None, 'object': oid, 'path': '<tag metadata>',
                                              **asdict(hit), 'commits': []}
                                             for hit in scan(data, '<tag metadata>'))
                    try:
                        header = dict(line.split(b' ', 1) for line in data.split(b'\n\n', 1)[0].splitlines())
                        target_kind, target_oid = header[b'type'].decode(), header[b'object'].decode()
                    except (ValueError, KeyError, UnicodeError):
                        raise ScanError('invalid_tag_object') from None
                    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', target_oid):
                        raise ScanError('invalid_tag_target')
                    pending.append((target_kind, target_oid))
                elif kind == 'tree':
                    snapshots[oid] = tree(git, oid)
                    extra_roots.add(oid)
                elif kind == 'blob':
                    snapshots[oid] = [(f'<blob ref {oid}>', oid)]
                    extra_roots.add(oid)
                elif kind != 'commit':
                    raise ScanError('unsupported_ref_object')
            scopes['history']['noncommit_roots'] = len(extra_roots)
            scopes['history']['metadata_objects'] = metadata_objects
        oids = sorted({oid for entries in snapshots.values() for _, oid in entries})
        paths_by_oid = {}
        for entries in snapshots.values():
            for path, oid in entries:
                paths_by_oid.setdefault(oid, set()).add(path)
        cache = {}
        for oid, data in git.blobs(oids):
            if data.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
                raise ScanError('external_lfs_content_not_scanned')
            for name in paths_by_oid[oid]:
                cache[oid, name] = scan(data, name)
                git.remaining()
        for label in ('head', 'history') if history else ('head',):
            scope = scopes[label]
            selected = [head] if label == 'head' else commits + sorted(extra_roots)
            versions, blobs, paths, env = set(), set(), set(), set()
            # Group identical secret+path across commits; never print secret values.
            findings = {}
            allowlisted = {}
            for commit in selected:
                for name, oid in snapshots[commit]:
                    versions.add((name, oid)); blobs.add(oid); paths.add(name)
                    if Path(name).name.startswith('.env'): env.add((name, oid))
                    for hit in cache[oid, name]:
                        key = (name, hit.kind, hit.fingerprint)
                        known_safe = label == 'history' and history_allowlisted(commit, name, hit)
                        destination = allowlisted if known_safe else findings
                        item = destination.setdefault(key, {'commit': None if commit in extra_roots else commit,
                                                         'path': name, **asdict(hit), 'commits': []})
                        if known_safe:
                            item['status'] = 'KNOWN_SAFE / ALLOWLISTED'
                        if commit in extra_roots:
                            item.setdefault('objects', []).append(commit)
                        else:
                            item['commits'].append(commit)
            scope.update(files=len(paths), file_versions=len(versions), unique_blobs=len(blobs), env_files=len(env),
                         findings=list(findings.values()), allowlisted=list(allowlisted.values()),
                         seconds=round(time.monotonic() - began, 3))
            if label == 'history':
                scope['findings'].extend(metadata_findings)
        report['unique_blobs_read'] = len(oids)
    except (ScanError, OSError) as error:
        # Git stderr/exception repr and file contents can contain secrets: omit them.
        report['error'] = str(error) if isinstance(error, ScanError) else 'filesystem_read_failed'
        for label, scope in scopes.items():
            if label != 'working_tree' or current_scope == 'working_tree':
                scope['status'] = 'INCOMPLETE'
    for scope in scopes.values():
        if scope['status'] != 'INCOMPLETE' and scope['findings']:
            scope['status'] = 'FAIL'
    report['seconds'] = round(time.monotonic() - start, 3)
    report['status'] = 'INCOMPLETE' if 'error' in report else 'FAIL' if any(s['findings'] for s in scopes.values()) else 'PASS'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='Include every commit reachable from local refs and HEAD')
    parser.add_argument('--repo', default='.', help='Repository root')
    parser.add_argument('--timeout', type=int, default=120, help='Total scan budget in seconds, checked between files (default: 120)')
    parser.add_argument('--json', action='store_true', help='Machine-readable safe report, no secret values')
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error('--timeout must be positive')
    report = audit(Path(args.repo).resolve(), history=args.history, timeout=args.timeout)
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        for label, scope in report['scopes'].items():
            print(f"{label}: {scope['status']} commits={scope['commits']} files={scope['files']} "
                  f"unique_blobs={scope['unique_blobs']} findings={len(scope['findings'])} "
                  f"allowlisted={len(scope['allowlisted'])} seconds={scope['seconds']}")
            for item in scope['findings'] + scope['allowlisted']:
                # JSON escaping also prevents control-character/terminal injection from paths.
                safe = {k: item[k] for k in ('commit', 'path', 'kind', 'fingerprint')}
                for key in ('object', 'objects', 'status'):
                    if key in item:
                        safe[key] = item[key]
                print(json.dumps(safe, ensure_ascii=True))
        if 'error' in report:
            print('INCOMPLETE: ' + report['error'])
        print(f"{report['status']}: runtime={report['seconds']}s; heuristic offline scan; no online validation")
    return {'PASS': 0, 'FAIL': 1, 'INCOMPLETE': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())

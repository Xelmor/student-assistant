"""Offline scanner regressions; all credentials below are generated fake data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.ci import scan_secrets as scanner


def fake_value():
    return 'Q7m4' + 'R8z2' * 9


def git(repo, *args):
    return subprocess.check_output(
        ['git', '-C', str(repo), *args], stderr=subprocess.PIPE,
        env={**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull},
    ).decode().strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Scanner test')
    git(tmp_path, 'config', 'user.email', 'scanner@example.invalid')
    (tmp_path / '.gitignore').write_text('.env\n*.pem\n')
    commit(tmp_path)
    return tmp_path


def commit(repo):
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'Scanner fixture', '--allow-empty')
    return git(repo, 'rev-parse', 'HEAD')


@pytest.mark.parametrize('key,kind', [
    ('TELEGRAM_BOT_TOKEN', 'telegram_bot_token'),
    ('TELEGRAM_WEBHOOK_SECRET', 'webhook_secret'),
    ('SECRET_KEY', 'secret_key'),
    ('API_KEY', 'api_key'),
    ('SMTP_PASSWORD', 'password'),
    ('RECOVERY_TOKEN', 'recovery_device_token'),
    ('DEVICE_TOKEN', 'recovery_device_token'),
])
@pytest.mark.parametrize('path', ['.env', '.env.production', 'settings.yaml'])
def test_literal_assignments(key, kind, path):
    value = fake_value()
    hits = scanner.scan(f'{key}={value}\n'.encode(), path)
    assert scanner.Hit(kind, scanner.fingerprint(value)) in hits
    assert value not in repr(hits)


@pytest.mark.parametrize('value,kind', [
    ('123456789:' + fake_value(), 'telegram_bot_token'),
    ('ghp_' + fake_value(), 'github_api_key'),
    ('AKIA' + 'B7C4' * 4, 'aws_access_key'),
    ('AIza' + ('B7c4' * 9)[:35], 'google_api_key'),
    ('sk-' + fake_value(), 'api_key'),
])
def test_provider_tokens_in_arbitrary_content(value, kind):
    assert scanner.Hit(kind, scanner.fingerprint(value)) in scanner.scan(
        b'\x00binary:' + value.encode(), 'asset.bin')


@pytest.mark.parametrize('scheme', ['postgresql', 'postgresql+psycopg', 'mysql', 'mongodb+srv', 'redis'])
def test_database_urls(scheme):
    value = fake_value()
    data = f'{scheme}://account:{value}@localhost/database'.encode()
    assert scanner.Hit('database_credentials', scanner.fingerprint(value)) in scanner.scan(data, 'config.txt')


def test_private_key_and_incomplete_key():
    header = '-----BEGIN ' + 'PRIVATE KEY-----'
    end = '-----END ' + 'PRIVATE KEY-----'
    assert any(h.kind == 'private_key' for h in scanner.scan(f'{header}\n{fake_value()}\n{end}'.encode(), 'key.pem'))
    assert any(h.kind == 'private_key' for h in scanner.scan(header.encode(), 'key.pem'))


def test_getenv_yaml_and_utf16():
    value = fake_value()
    samples = [
        (f'os.getenv("SECRET_KEY", "{value}")', 'app.py'),
        (f'- key: TELEGRAM_WEBHOOK_SECRET\n  value: {value}', 'render.yaml'),
    ]
    for data, path in samples:
        assert scanner.scan(data.encode(), path)
    assert scanner.scan(f'PASSWORD={value}'.encode('utf-16'), '.env')


def test_short_password_is_not_ignored_outside_documentation():
    def assignment(value):
        return b'password' + b'=' + value

    assert scanner.scan(assignment(b'1'), '.env')
    assert scanner.scan(assignment(b'"None"'), 'config.py')
    assert not scanner.scan(assignment(b'None'), 'config.py')


def test_regression_source_does_not_contain_literal_secrets():
    assert not scanner.scan(Path(__file__).read_bytes(), 'tests/test_secret_scanner.py')


@pytest.mark.parametrize('value', ['<token>', '${TOKEN}', 'your-token-here', 'replace_me', 'change_me', 'example-password'])
def test_documentation_placeholders(value):
    assert not scanner.scan(f'SECRET_KEY={value}\n'.encode(), 'README.md')


def test_empty_values_references_and_metadata_are_not_credentials():
    data = b'''TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=
OTHER_SETTING=non_secret
'''
    assert not scanner.scan(data, '.env.example')
    assert not scanner.scan(b'''password = request.password
token = make_token()
password_hash="hash"
''', 'app.py')
    assert not scanner.scan(b'--password-recovery: 10px;', 'style.css')
    assert not scanner.scan(b'TOKEN_TTL_SECONDS=3600', '.env')


def test_test_named_file_or_substring_does_not_hide_provider_token():
    value = '123456789:' + fake_value() + 'test'
    assert scanner.scan(value.encode(), 'tests/test_tokens.py')
    assert scanner.scan('='.join(('SECRET_KEY', f'"{fake_value()}-test"')).encode(), 'tests/test_tokens.py')
    assert scanner.scan(b'SECRET_KEY=dev-not-a-placeholder-in-production', '.env.production')


def test_reviewed_examples_are_exact_path_type_and_value(monkeypatch):
    value = fake_value()
    monkeypatch.setattr(scanner, 'REVIEWED_EXAMPLES', {('tests/fixture.py', 'secret_key', scanner.fingerprint(value))})
    data = f'SECRET_KEY="{value}"'.encode()
    assert not scanner.scan(data, 'tests/fixture.py')
    assert scanner.scan(data, 'app.py')
    assert scanner.scan(data.replace(value.encode(), (value + 'A').encode()), 'tests/fixture.py')
    assert scanner.scan(data.replace(b'SECRET_KEY', b'API_KEY'), 'tests/fixture.py')


def historical_fallback():
    # Reconstruct the reviewed public development literal, without embedding a
    # credential assignment in this test source or printing the literal.
    return '_'.join(('dev', 'secret', 'change', 'me'))


def allow_fixture_commit(monkeypatch, commit_id):
    monkeypatch.setattr(scanner, 'KNOWN_SAFE_HISTORY', {
        ('app/main.py', 'secret_key', 'sha256:376912d192756c41'): frozenset({commit_id}),
    })


def test_known_history_rule_is_exact():
    old = '969bb1548ef65fefd2de118c3e67e508f86b8240'
    hit = scanner.Hit('secret_key', 'sha256:376912d192756c41')
    assert scanner.fingerprint(historical_fallback()) == hit.fingerprint
    assert scanner.history_allowlisted(old, 'app/main.py', hit)
    assert not scanner.history_allowlisted(old, 'other/main.py', hit)
    assert not scanner.history_allowlisted(old, 'app/main.py', scanner.Hit('api_key', hit.fingerprint))
    assert not scanner.history_allowlisted(old, 'app/main.py', scanner.Hit(hit.kind, scanner.fingerprint(fake_value())))
    assert not scanner.history_allowlisted('0' * 40, 'app/main.py', hit)


@pytest.mark.parametrize('path,key,value,expected', [
    ('app/main.py', 'SECRET_KEY', historical_fallback(), 'PASS'),
    ('app/main.py', 'SECRET_KEY', fake_value(), 'FAIL'),
    ('other/main.py', 'SECRET_KEY', historical_fallback(), 'FAIL'),
    ('app/main.py', 'TELEGRAM_BOT_TOKEN', '123456789:' + fake_value(), 'FAIL'),
    ('settings.py', 'SECRET_KEY', fake_value(), 'FAIL'),
    ('app/main.py', 'APP_NAME', 'student-assistant', 'PASS'),
])
def test_history_allowlist_preserves_failures(repo, monkeypatch, path, key, value, expected):
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(f'{key}="{value}"')
    old = commit(repo)
    allow_fixture_commit(monkeypatch, old)
    file.unlink()
    commit(repo)
    result = scanner.audit(repo, history=True)
    history = result['scopes']['history']
    assert result['status'] == history['status'] == expected
    assert result['scopes']['head']['status'] == 'PASS'
    assert result['scopes']['working_tree']['status'] == 'PASS'
    if value == historical_fallback() and path == 'app/main.py':
        assert history['allowlisted'][0]['status'] == 'KNOWN_SAFE / ALLOWLISTED'
        assert history['allowlisted'][0]['commits'] == [old]
    else:
        assert not history['allowlisted']
    assert value not in json.dumps(result)


def test_history_allowlist_never_applies_to_head_or_working_tree(repo, monkeypatch):
    file = repo / 'app/main.py'
    file.parent.mkdir()
    file.write_text(f'SECRET_KEY="{historical_fallback()}"')
    old = commit(repo)
    allow_fixture_commit(monkeypatch, old)
    result = scanner.audit(repo, history=True)
    assert result['scopes']['history']['status'] == 'PASS'
    for label in ('working_tree', 'head'):
        assert result['scopes'][label]['status'] == 'FAIL'
        assert not result['scopes'][label]['allowlisted']
    assert result['status'] == 'FAIL'


def test_same_finding_in_unreviewed_commit_still_fails(repo, monkeypatch):
    file = repo / 'app/main.py'
    file.parent.mkdir()
    file.write_text(f'SECRET_KEY="{historical_fallback()}"')
    old = commit(repo)
    new = commit(repo)
    allow_fixture_commit(monkeypatch, old)
    file.unlink()
    commit(repo)
    history = scanner.audit(repo, history=True)['scopes']['history']
    assert history['status'] == 'FAIL'
    assert history['allowlisted'][0]['commits'] == [old]
    assert history['findings'][0]['commits'] == [new]


def test_known_history_visible_in_cli_and_does_not_hide_new_secret(repo, monkeypatch, capsys):
    file = repo / 'app/main.py'
    file.parent.mkdir()
    file.write_text(f'SECRET_KEY="{historical_fallback()}"')
    allow_fixture_commit(monkeypatch, commit(repo))
    file.unlink()
    commit(repo)
    assert scanner.main(['--repo', str(repo), '--history']) == 0
    output = capsys.readouterr().out
    assert 'history: PASS' in output
    assert 'KNOWN_SAFE / ALLOWLISTED' in output
    assert historical_fallback() not in output
    file.write_text(f'SECRET_KEY="{fake_value()}"')
    commit(repo)
    file.unlink()
    commit(repo)
    assert scanner.main(['--repo', str(repo), '--history', '--json']) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['scopes']['history']['status'] == 'FAIL'
    assert len(report['scopes']['history']['allowlisted']) == 1
    assert len(report['scopes']['history']['findings']) == 1


def test_deleted_secret_on_other_branch_and_separate_scopes(repo):
    branch = git(repo, 'branch', '--show-current')
    git(repo, 'checkout', '-qb', 'historical-branch')
    path = repo / 'old credentials.env'
    value = fake_value()
    path.write_text(f'SECRET_KEY="{value}"')
    old = commit(repo)
    path.unlink()
    commit(repo)
    git(repo, 'checkout', '-q', branch)
    (repo / '.env').write_text(f'TELEGRAM_BOT_TOKEN={value}')
    result = scanner.audit(repo, history=True)
    assert result['status'] == 'FAIL'
    assert result['scopes']['head']['status'] == 'PASS'
    assert result['scopes']['working_tree']['findings'][0]['tracked'] is False
    historical = result['scopes']['history']
    assert historical['commits'] == 3
    assert historical['findings'][0]['commit'] == old
    assert historical['findings'][0]['path'] == path.name
    assert value not in json.dumps(result)


def test_working_tree_changes_do_not_replace_head_scan(repo):
    path = repo / 'config.py'
    path.write_text(f'SECRET_KEY="{fake_value()}"')
    commit(repo)
    path.write_text('SECRET_KEY = from_environment()')
    result = scanner.audit(repo)
    assert result['scopes']['working_tree']['status'] == 'PASS'
    assert result['scopes']['head']['status'] == 'FAIL'


def test_metadata_and_noncommit_refs_are_not_skipped(repo):
    value = fake_value()
    git(repo, 'commit', '-qm', f'SECRET_KEY={value}', '--allow-empty')
    git(repo, 'tag', '-a', 'annotated', '-m', f'API_KEY={value}')
    (repo / 'snapshot.env').write_text(f'DEVICE_TOKEN={value}')
    git(repo, 'add', 'snapshot.env')
    snapshot = git(repo, 'write-tree')
    git(repo, 'update-ref', 'refs/snapshots/scan', snapshot)
    blob = git(repo, 'rev-parse', ':snapshot.env')
    git(repo, 'update-ref', 'refs/snapshots/blob', blob)
    git(repo, 'reset', '-q', 'HEAD')
    (repo / 'snapshot.env').unlink()
    result = scanner.audit(repo, history=True)
    historical = result['scopes']['history']
    assert historical['noncommit_roots'] == 2
    assert historical['metadata_objects'] == 3
    assert {h['kind'] for h in historical['findings']} == {'secret_key', 'api_key', 'recovery_device_token'}
    assert result['scopes']['head']['status'] == 'PASS'
    assert result['scopes']['working_tree']['status'] == 'PASS'
    assert value not in json.dumps(result)


def test_each_blob_read_once_with_renames_and_empty_commits(repo, monkeypatch):
    (repo / 'first.txt').write_text('clean\n')
    commit(repo)
    (repo / 'first.txt').rename(repo / 'renamed.txt')
    commit(repo)
    for _ in range(8):
        commit(repo)
    calls = []
    original = scanner.Git.blobs

    def record(self, oids):
        calls.extend(oids)
        yield from original(self, oids)

    monkeypatch.setattr(scanner.Git, 'blobs', record)
    result = scanner.audit(repo, history=True)
    assert result['status'] == 'PASS'
    assert result['scopes']['history']['commits'] == 11
    assert len(calls) == len(set(calls)) == 2
    assert result['scopes']['history']['file_versions'] == 3


def test_ignored_key_files_and_large_binary_are_scanned(repo):
    header = '-----BEGIN ' + 'PRIVATE KEY-----'
    (repo / 'ignored.pem').write_text(header)
    (repo / 'large.bin').write_bytes(b'\0' * 2_000_000 + ('123456789:' + fake_value()).encode())
    result = scanner.audit(repo)
    assert {h['path'] for h in result['scopes']['working_tree']['findings']} == {'ignored.pem', 'large.bin'}


def test_symlinks_not_followed(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp('outside') / 'credential'
    outside.write_text(f'SECRET_KEY={fake_value()}')
    (repo / 'link').symlink_to(outside)
    (repo / 'directory-link').symlink_to(outside.parent, target_is_directory=True)
    assert scanner.audit(repo)['status'] == 'PASS'


def test_shallow_history_fails_closed(repo):
    (repo / '.git/shallow').write_text(git(repo, 'rev-parse', 'HEAD') + '\n')
    result = scanner.audit(repo, history=True)
    assert result['status'] == 'INCOMPLETE'
    assert 'shallow_history' in result['error']


def test_lfs_fails_closed(repo):
    (repo / 'external').write_text('version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n')
    commit(repo)
    assert scanner.audit(repo, history=True)['status'] == 'INCOMPLETE'


def test_missing_object_fails_closed(repo):
    (repo / 'missing').write_text('will become unavailable')
    commit(repo)
    oid = git(repo, 'rev-parse', 'HEAD:missing')
    (repo / '.git/objects' / oid[:2] / oid[2:]).unlink()
    result = scanner.audit(repo, history=True)
    assert result['status'] == 'INCOMPLETE'


def test_timeout_is_shared_between_git_reads(repo, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(scanner.time, 'monotonic', lambda: clock[0])
    client = scanner.Git(repo, 2)
    assert client.remaining() == 2
    clock[0] += 1.5
    assert client.remaining() == .5
    clock[0] += .6
    with pytest.raises(scanner.ScanError, match='scan_timeout'):
        client.run('rev-parse', 'HEAD')


def test_git_io_timeout_returns_incomplete(repo, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('git', 1, stderr=fake_value().encode())

    monkeypatch.setattr(scanner.subprocess, 'check_output', timeout)
    result = scanner.audit(repo, history=True)
    assert result['status'] == 'INCOMPLETE'
    assert fake_value() not in json.dumps(result)


def test_unreachable_commits_are_outside_scope(repo):
    initial = git(repo, 'rev-parse', 'HEAD')
    (repo / 'old.env').write_text(f'SECRET_KEY={fake_value()}')
    commit(repo)
    git(repo, 'reset', '--hard', initial)
    result = scanner.audit(repo, history=True)
    assert result['status'] == 'PASS'
    assert result['scopes']['history']['commits'] == 1


def test_git_failure_never_prints_stderr(repo, monkeypatch):
    def unavailable(*args, **kwargs):
        raise subprocess.CalledProcessError(1, 'git', stderr=fake_value().encode())

    monkeypatch.setattr(scanner.subprocess, 'check_output', unavailable)
    result = scanner.audit(repo, history=True)
    assert result['status'] == 'INCOMPLETE'
    assert fake_value() not in json.dumps(result)


def test_cli_safe_json_and_exit_codes(repo):
    script = Path(scanner.__file__).resolve()

    def run():
        return subprocess.run([sys.executable, str(script), '--repo', str(repo), '--history', '--json'],
                              capture_output=True, text=True, timeout=10)

    assert run().returncode == 0
    value = fake_value()
    (repo / 'config.env').write_text(f'SECRET_KEY={value}')
    found = run()
    assert found.returncode == 1
    assert json.loads(found.stdout)['status'] == 'FAIL'
    assert value not in found.stdout + found.stderr
    (repo / '.git/shallow').write_text(git(repo, 'rev-parse', 'HEAD') + '\n')
    assert run().returncode == 2

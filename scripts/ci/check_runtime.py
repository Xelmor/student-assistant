"""Verify installed runtime pins, constraints, and optional before/after snapshot."""
import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def read_pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '--hash=')):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s;\\]+)\s*\\?', line)
        if not match:
            raise ValueError(f'Expected an exact pin in {path.name}: {line}')
        name = re.sub(r'[-_.]+', '-', match[1]).lower()
        if name in pins:
            raise ValueError(f'Duplicate pin: {name}')
        pins[name] = match[2]
    if not pins:
        raise ValueError(f'No pins in {path.name}')
    return pins


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--production-only', action='store_true')
    args = parser.parse_args()
    expected = read_pins(ROOT / 'requirements.lock.txt')
    if expected != read_pins(ROOT / 'requirements.constraints.txt'):
        raise SystemExit('Runtime constraints differ from production lock')
    actual = {name: metadata.version(name) for name in expected}
    if actual != expected:
        differences = {name: (expected[name], actual[name]) for name in expected
                       if expected[name] != actual[name]}
        raise SystemExit(f'Runtime versions differ (expected, installed): {differences}')
    if args.baseline and actual != json.loads(args.baseline.read_text(encoding='utf-8')):
        raise SystemExit('Runtime versions changed after dev installation')
    if args.production_only:
        installed = {re.sub(r'[-_.]+', '-', d.metadata['Name']).lower()
                     for d in metadata.distributions()}
        # A fresh venv may contain packaging tools, but no unpinned runtime/dev packages.
        unexpected = installed - expected.keys() - {'pip', 'setuptools', 'wheel'}
        if unexpected:
            raise SystemExit(f'Unexpected packages in production environment: {sorted(unexpected)}')
    if args.snapshot:
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.snapshot.write_text(json.dumps(actual, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'PASS: {len(actual)} runtime versions match lock and constraints')


if __name__ == '__main__':
    main()

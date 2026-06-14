from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


E2E_DIRECTORY = (Path(__file__).resolve().parent / 'e2e').resolve()


def pytest_ignore_collect(collection_path, config):
    """Keep browser tests out of the ordinary unit/integration test run."""
    path = Path(str(collection_path)).resolve()
    if path != E2E_DIRECTORY and E2E_DIRECTORY not in path.parents:
        return False

    invocation_args = config.invocation_params.args
    for raw_arg in invocation_args:
        if raw_arg.startswith('-'):
            continue
        candidate = raw_arg.split('::', 1)[0]
        if not candidate:
            continue
        resolved = (Path(config.invocation_params.dir) / candidate).resolve()
        if resolved == E2E_DIRECTORY or E2E_DIRECTORY in resolved.parents:
            return False
    return True

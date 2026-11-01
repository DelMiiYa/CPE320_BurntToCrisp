"""Run repository and/or website tests with isolated runtime data; never calls a model."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--website', action='store_true', help='Test BurningUpp only')
    parser.add_argument('--all', action='store_true', help='Test Office and BurningUpp')
    parser.add_argument('--website-timeout', type=int, default=300, help='Website test deadline in seconds (default: 300 for slower CI runners)')
    args = parser.parse_args()
    if args.website_timeout <= 0:
        parser.error('--website-timeout must be positive')
    with tempfile.TemporaryDirectory(prefix='office-check-') as tmp:
        # Keep framework caches as well as application data out of the user's folders.
        os.environ.update(
            CREWAI_STORAGE_DIR=str(Path(tmp)/'crewai'),
            PYTHON_DOTENV_DISABLED='1', CREWAI_TELEMETRY_DISABLED='true',
            OTEL_SDK_DISABLED='true', PYTHONDONTWRITEBYTECODE='1',
        )
        if not args.website or args.all:
            env = os.environ.copy()
            env['APP_DATA_DIR'] = str(Path(tmp)/'data')
            # Provider tests select mocks explicitly, independent of the developer's shell/.env.
            env.pop('AGENT_BACKEND', None)
            result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests'],cwd=ROOT,env=env)
            if result.returncode:
                return result.returncode
        if args.website or args.all:
            from se_team.tools.sandbox import SandboxManager
            box = SandboxManager(ROOT / 'websites/BurningUpp', retain_artifacts=False)
            result = box.run_tests('tests', timeout=args.website_timeout)
            print(result['output'])
            if not result['passed']:
                return max(1, result['exit_code'])
            print(f"BurningUpp: {result['tests_passed']}/{result['tests_executed']} passed (temporary data)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

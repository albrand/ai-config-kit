#!/usr/bin/env python3
"""Run tracked, self-contained tests; host installation checks stay separate."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
HOST_CHECK = 'skillsets/qa-enforcement/hooks/test-hook-chain.sh'
TEST_NAME = re.compile(r'(?:test(?:[_-].*)?|.*(?:_test|\.test))\.(?:py|sh|mjs|js|cjs)$')


def inventory(repo=ROOT):
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=repo, capture_output=True, check=True)
    return sorted(p for p in result.stdout.decode().split('\0')
                  if p and TEST_NAME.fullmatch(Path(p).name) and p != HOST_CHECK)


def command(path):
    if path.suffix == '.py':
        return [sys.executable, str(path)]
    if path.suffix == '.sh':
        shell = 'bash' if 'bash' in path.read_text().splitlines()[0] else 'sh'
        return [shell, str(path)]
    return ['node', str(path)]


def main():
    tests = inventory()
    if not tests:
        print('FAIL empty self-contained test inventory', flush=True)
        return 1
    failed = []
    for name in tests:
        print(f'== {name}', flush=True)
        result = subprocess.run(command(ROOT / name), cwd=ROOT)
        print(f'{"PASS" if result.returncode == 0 else "FAIL"} {name} (exit {result.returncode})', flush=True)
        if result.returncode:
            failed.append(name)
    # This CLI selftest does not follow a test-file naming convention.
    gate = ROOT / 'skillsets/qa-enforcement/shared/qa-sweep/scripts/ship-gate.py'
    result = subprocess.run([sys.executable, str(gate), 'selftest'], cwd=ROOT)
    if result.returncode:
        failed.append('ship-gate selftest')
    print(f'unit: {len(tests)} test files + ship-gate selftest; {len(failed)} failed', flush=True)
    print(f'host-only check excluded: {HOST_CHECK}', flush=True)
    return int(bool(failed))


if __name__ == '__main__':
    sys.exit(main())

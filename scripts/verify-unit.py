#!/usr/bin/env python3
"""Run tracked, self-contained tests; host installation checks stay separate."""
from pathlib import Path
import ast
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
TEST_NAME = re.compile(r'(?:test(?:[_-].*)?|.*(?:_test|\.test))\.(?:py|sh|mjs|js|cjs)$')


def python_markers(path):
    if path.suffix != '.py':
        return False, False, False
    try:
        tree = ast.parse(path.read_bytes())
    except SyntaxError:
        return False, False, False  # The static stage fails malformed source.
    modules = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.Import)
               for a in n.names if a.name == 'unittest'}
    cases = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
             and n.module == 'unittest' for a in n.names if a.name == 'TestCase'}
    mains = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
             and n.module == 'unittest' for a in n.names if a.name == 'main'}

    def member(node, name):
        return isinstance(node, ast.Attribute) and node.attr == name \
            and isinstance(node.value, ast.Name) and node.value.id in modules

    suite = any(isinstance(n, ast.ClassDef) and any(member(b, 'TestCase')
                or isinstance(b, ast.Name) and b.id in cases for b in n.bases) for n in ast.walk(tree))
    entry = any(isinstance(n, ast.Call) and (member(n.func, 'main')
                or isinstance(n.func, ast.Name) and n.func.id in mains) for n in ast.walk(tree))
    embedded = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'selftest' for n in tree.body)
    return suite, entry, embedded


def registry(repo):
    path = repo / 'scripts/verify-suites.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    return data.get('selftests', {}), data.get('excluded', {})


def inventory(repo=ROOT):
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=repo, capture_output=True, check=True)
    tracked = {p for p in result.stdout.decode().split('\0') if p}
    selftests, excluded = registry(repo)
    for name, args in selftests.items():
        if name not in tracked or args not in (['selftest'], ['--selftest']):
            raise ValueError(f'invalid registered selftest: {name}')
    for name, reason in excluded.items():
        if name not in tracked or not isinstance(reason, str) or not reason.strip():
            raise ValueError(f'invalid suite exclusion: {name}')
    tests = []
    for name in sorted(tracked):
        if name in excluded or name in selftests:
            continue
        path = repo / name
        suite, _, embedded = python_markers(path)
        if embedded:
            raise ValueError(f'unregistered embedded selftest: {name}; declare its offline invocation')
        node_suite = path.suffix in ('.js', '.mjs', '.cjs') and re.search(
            r"(?:^|\n)\s*import\b[^;]*\bfrom\s*['\"]node:test['\"]|\brequire\(\s*['\"]node:test['\"]\s*\)", path.read_text())
        if suite or node_suite or TEST_NAME.fullmatch(path.name):
            tests.append(name)
    return tests


def command(path, args=()):
    if path.suffix == '.py':
        suite, entry, _ = python_markers(path)
        if suite and not entry and not args:
            return [sys.executable, '-m', 'unittest', str(path.relative_to(ROOT))]
        return [sys.executable, str(path), *args]
    if path.suffix == '.sh':
        shell = 'bash' if 'bash' in path.read_text().split('\n', 1)[0] else 'sh'
        return [shell, str(path), *args]
    return ['node', str(path), *args]


def main():
    tests = inventory()
    selftests, excluded = registry(ROOT)
    if not tests and not selftests:
        print('FAIL empty self-contained test inventory', flush=True)
        return 1
    failed = []
    for name, args in [(name, ()) for name in tests] + sorted(selftests.items()):
        print(f'== {name}', flush=True)
        result = subprocess.run(command(ROOT / name, args), cwd=ROOT)
        print(f'{"PASS" if result.returncode == 0 else "FAIL"} {name} (exit {result.returncode})', flush=True)
        if result.returncode:
            failed.append(name)
    print(f'unit: {len(tests)} test files + {len(selftests)} CLI selftests; {len(failed)} failed', flush=True)
    for name in failed:
        print(f'failed suite: {name}', flush=True)
    for name, reason in sorted(excluded.items()):
        print(f'host-only check excluded: {name}: {reason}', flush=True)
    return int(bool(failed))


if __name__ == '__main__':
    sys.exit(main())

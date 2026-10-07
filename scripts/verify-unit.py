#!/usr/bin/env python3
"""Run tracked, self-contained tests; host installation checks stay separate."""
from pathlib import Path
import ast
import json
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
TEST_NAME = re.compile(r'(?:test(?:[_-].*)?|.*(?:_test|\.test))\.(?:py|sh|mjs|js|cjs)$')
UNITTEST_BASES = set()
for exported in unittest.__all__:
    value = getattr(unittest, exported)
    if isinstance(value, type) and issubclass(value, unittest.TestCase):
        UNITTEST_BASES.add(('unittest', exported))
        UNITTEST_BASES.add(tuple(value.__module__.split('.')) + (value.__name__,))


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
    def main_guard(node):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 \
                or not isinstance(node.ops[0], ast.Eq) or len(node.comparators) != 1:
            return False
        pair = (node.left, node.comparators[0])
        return any(isinstance(a, ast.Name) and a.id == '__name__'
                   and isinstance(b, ast.Constant) and b.value == '__main__'
                   for a, b in (pair, pair[::-1]))

    def calls_main(body):
        # A call in an unused helper or a false branch does not run the suite.
        # Only recognize direct calls and the conventional script entry guard.
        for node in body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                func = node.value.func
                if member(func, 'main') or isinstance(func, ast.Name) and func.id in mains:
                    return True
            elif isinstance(node, ast.If) and main_guard(node.test) and calls_main(node.body):
                return True
        return False

    entry = calls_main(tree.body)
    embedded = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'selftest' for n in tree.body)
    return suite, entry, embedded


def registry(repo):
    path = repo / 'scripts/verify-suites.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    return data.get('selftests', {}), data.get('excluded', {})


def unittest_suites(repo, tracked):
    """Resolve tracked TestCase inheritance without importing repository code.

    Suffix matches also cover packages placed on sys.path by their local runner.
    Ambiguous suffixes include every matching test base rather than dropping a suite.
    """
    classes = {}
    owners = {}
    for name in sorted(tracked):
        path = repo / name
        if path.suffix != '.py':
            continue
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            continue  # Reported by the static stage.
        module = tuple(path.relative_to(repo).with_suffix('').parts)
        package = module[:-1]
        if module[-1] == '__init__':
            module = package
        bindings = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bindings[alias.asname or alias.name.split('.')[0]] = tuple(
                        alias.name.split('.') if alias.asname else [alias.name.split('.')[0]])
            elif isinstance(node, ast.ImportFrom):
                prefix = package[:len(package) - node.level + 1] if node.level else ()
                imported = prefix + tuple((node.module or '').split('.')) if node.module else prefix
                for alias in node.names:
                    bindings[alias.asname or alias.name] = imported + (alias.name,)

        def target(node):
            if isinstance(node, ast.Name):
                return bindings.get(node.id, module + (node.id,))
            if isinstance(node, ast.Attribute):
                parent = target(node.value)
                return parent + (node.attr,) if parent else ()
            return ()

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                key = module + (node.name,)
                classes[key] = [target(base) for base in node.bases]
                owners[key] = name
    resolved = {key for key, bases in classes.items() if any(base in UNITTEST_BASES for base in bases)}
    while True:
        additions = {key for key, bases in classes.items() if key not in resolved and any(
            base and any(parent == base or len(parent) >= len(base) and parent[-len(base):] == base
                         for parent in resolved) for base in bases)}
        if not additions:
            return {owners[key] for key in resolved}
        resolved.update(additions)


def inventory(repo=ROOT):
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=repo, capture_output=True, check=True)
    tracked = {p for p in result.stdout.decode().split('\0') if p}
    selftests, excluded = registry(repo)
    suites = unittest_suites(repo, tracked)
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
        if name in suites or suite or node_suite or TEST_NAME.fullmatch(path.name):
            tests.append(name)
    return tests


def command(path, args=(), inherited_suite=False):
    if path.suffix == '.py':
        suite, entry, _ = python_markers(path)
        if (suite or inherited_suite) and not entry and not args:
            return [sys.executable, '-m', 'unittest', str(path.relative_to(ROOT))]
        return [sys.executable, str(path), *args]
    if path.suffix == '.sh':
        shell = 'bash' if 'bash' in path.read_text().split('\n', 1)[0] else 'sh'
        return [shell, str(path), *args]
    return ['node', str(path), *args]


def main():
    tests = inventory()
    selftests, excluded = registry(ROOT)
    # Include support modules so inheritance resolution sees imported bases too.
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    suites = unittest_suites(ROOT, [name for name in tracked if name])
    if not tests and not selftests:
        print('FAIL empty self-contained test inventory', flush=True)
        return 1
    failed = []
    for name, args in [(name, ()) for name in tests] + sorted(selftests.items()):
        print(f'== {name}', flush=True)
        result = subprocess.run(command(ROOT / name, args, name in suites), cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
        print(result.stdout, end='', flush=True)
        print(f'{"PASS" if result.returncode == 0 else "FAIL"} {name} (exit {result.returncode})', flush=True)
        if result.returncode:
            failure_log = ROOT / '.verify/runs/unit-failures' / (name + '.log')
            failure_log.parent.mkdir(parents=True, exist_ok=True)
            failure_log.write_text(result.stdout)
            failed.append((name, result.stdout, failure_log))
    print(f'unit: {len(tests)} test files + {len(selftests)} CLI selftests; {len(failed)} failed', flush=True)
    for name, output, failure_log in failed:
        print(f'failed suite: {name}', flush=True)
        print(f'failure output retained: {failure_log.relative_to(ROOT)}', flush=True)
        print(output[-2000:], end='', flush=True)
    for name, reason in sorted(excluded.items()):
        print(f'host-only check excluded: {name}: {reason}', flush=True)
    return int(bool(failed))


if __name__ == '__main__':
    sys.exit(main())

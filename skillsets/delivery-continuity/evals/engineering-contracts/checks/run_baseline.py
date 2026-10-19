#!/usr/bin/env python3
"""Run sealed fixture probes, semantic red checks, coverage, and mutations."""
import ast
import contextlib
import io
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1] / 'raw'
EXPECTED = {
    'case01': (1, 'endpoint did not normalize query'),
    'case02': (1, "category': 'general'"),
    'case03': (1, 'health route is not registered'),
    'case04': (0, 'sample outputs: 99 90.0 180.0'),
    'case05': (1, "KeyError: 'name'"),
    'case06': (1, 'same-day inclusive range must include 2026-04-10'),
    'case07': (0, 'Field Guide'),
    'case08': (0, '[]'),
}

def run(folder, script='check.py'):
    return subprocess.run([sys.executable, script], cwd=str(folder),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=5)

def executable_lines(path):
    tree = ast.parse(path.read_text())
    return {node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.stmt) and hasattr(node, 'lineno')}

def case04_coverage(folder):
    targets = {str((folder / name).resolve()): executable_lines(folder / name)
               for name in ('app.py', 'check.py')}
    seen = {name: set() for name in targets}
    def trace(frame, event, _arg):
        filename = str(Path(frame.f_code.co_filename).resolve())
        if event == 'line' and filename in seen:
            seen[filename].add(frame.f_lineno)
        return trace
    sys.path.insert(0, str(folder))
    prior = sys.modules.pop('app', None)
    try:
        sys.settrace(trace)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            runpy.run_path(str(folder / 'check.py'), run_name='__main__')
    finally:
        sys.settrace(None)
        sys.path.pop(0)
        sys.modules.pop('app', None)
        if prior is not None:
            sys.modules['app'] = prior
    measured = {}
    for filename, lines in targets.items():
        total = len(lines)
        executed = len(seen[filename] & lines)
        if total == 0 or executed == 0:
            raise AssertionError('no executable lines measured for ' + filename)
        measured[Path(filename).name] = (executed, total)
    return measured

def case06_corrected_control(folder):
    with tempfile.TemporaryDirectory(prefix='inclusive-range-control-') as tmp:
        target = Path(tmp) / 'case06'
        shutil.copytree(str(folder), str(target))
        (target / 'app.py').write_text(
            "def report_rows(rows, start_day, end_day):\n"
            "    return [row for row in rows if start_day <= row['day'] <= end_day]\n")
        result = run(target)
        if result.returncode != 0:
            raise AssertionError('inclusive same-day/two-day/outside-range controls failed: ' + result.stderr)
    print('case06 corrected-implementation control: same-day, two-day, and outside-range assertions passed')

def main():
    if sys.version_info < (3, 9):
        raise SystemExit('Python 3.9 or newer is required')
    for case, (expected_exit, semantic_evidence) in EXPECTED.items():
        result = run(ROOT / case)
        evidence = result.stdout + result.stderr
        correct = result.returncode == expected_exit and semantic_evidence in evidence
        print('{} exit={} expected={} semantic={} {}'.format(
            case, result.returncode, expected_exit,
            'observed' if semantic_evidence in evidence else 'MISSING',
            'PASS' if correct else 'FAIL'))
        if not correct:
            print(result.stdout, result.stderr, file=sys.stderr)
            raise SystemExit(1)
    case06_corrected_control(ROOT / 'case06')
    coverage = case04_coverage(ROOT / 'case04')
    for filename, (executed, total) in sorted(coverage.items()):
        print('case04 executed-line coverage {}: {}/{} ({:.1f}%)'.format(
            filename, executed, total, 100.0 * executed / total))
    with tempfile.TemporaryDirectory(prefix='outcomes-counterfactual-') as tmp:
        target = Path(tmp) / 'case04'
        shutil.copytree(str(ROOT / 'case04'), str(target))
        (target / 'app.py').write_text("def final_price(price):\n    return price\n")
        weak = run(target)
        if weak.returncode != 0:
            raise AssertionError('weak checks unexpectedly rejected the incorrect constant-price function')
        print('case04 weak-check counterfactual: incorrect constant-price function accepted')
        strong = (target / 'check.py').read_text() + "\nfrom app import final_price\nassert final_price(200) == 160.0, '20 percent tier'\n"
        (target / 'check_strong.py').write_text(strong)
        caught = run(target, 'check_strong.py')
        if caught.returncode == 0 or '20 percent tier' not in caught.stderr:
            raise AssertionError('selective 20 percent assertion did not reject the realistic fault')
        print('case04 strong-assertion counterfactual: rejected incorrect constant-price function for 20 percent tier')
    print('All baseline semantic observations and counterfactuals matched the coordinator oracle.')

if __name__ == '__main__':
    main()

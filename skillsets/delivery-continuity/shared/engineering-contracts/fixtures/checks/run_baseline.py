#!/usr/bin/env python3
"""Run the sealed fixture probes and one assertion-strength counterfactual."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1] / 'raw'
EXPECTED = {'case01': 1, 'case02': 1, 'case03': 1, 'case04': 0,
            'case05': 1, 'case06': 1, 'case07': 0, 'case08': 0}

def run(folder):
    return subprocess.run([sys.executable, 'check.py'], cwd=str(folder),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=5)

def main():
    if sys.version_info < (3, 9):
        raise SystemExit('Python 3.9 or newer is required')
    for case, expected in EXPECTED.items():
        result = run(ROOT / case)
        print('{} exit={} expected={} {}'.format(
            case, result.returncode, expected,
            'PASS' if result.returncode == expected else 'FAIL'))
        if result.returncode != expected:
            print(result.stdout, result.stderr, file=sys.stderr)
            raise SystemExit(1)
    with tempfile.TemporaryDirectory(prefix='outcomes-counterfactual-') as tmp:
        target = Path(tmp) / 'case04'
        shutil.copytree(str(ROOT / 'case04'), str(target))
        source = target / 'app.py'
        source.write_text("def final_price(price):\n    return price\n")
        mutated = run(target)
        if mutated.returncode != 0:
            print('case04 counterfactual unexpectedly detected a wrong result',
                  mutated.stdout, mutated.stderr, file=sys.stderr)
            raise SystemExit(1)
        print('case04 counterfactual exit=0 despite incorrect pricing: weak checks do not detect it')
    print('All baseline observations matched the coordinator oracle.')

if __name__ == '__main__':
    main()

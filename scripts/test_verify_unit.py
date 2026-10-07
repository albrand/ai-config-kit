"""Exercise test discovery and failure propagation through the stage CLI."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class UnitStageTests(unittest.TestCase):
    def test_nested_failure_is_found_and_later_suites_still_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            (root / 'scripts').mkdir()
            source = Path(__file__).with_name('verify-unit.py')
            (root / 'scripts/verify-unit.py').write_text(source.read_text())
            tests = root / 'skillsets/new-skill/tests'
            tests.mkdir(parents=True)
            (tests / 'a_test.py').write_text('print("NESTED FAILURE exercised")\nraise SystemExit(1)\n')
            (tests / 'z_test.py').write_text('print("LATER SUITE exercised")\n')
            gate = root / 'skillsets/qa-enforcement/shared/qa-sweep/scripts/ship-gate.py'
            gate.parent.mkdir(parents=True)
            gate.write_text('print("SELFTEST exercised")\n')
            host = root / 'skillsets/qa-enforcement/hooks/test-hook-chain.sh'
            host.parent.mkdir(parents=True)
            host.write_text('#!/bin/sh\necho HOST-ONLY-CHECK-RAN\nexit 1\n')
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            result = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('NESTED FAILURE exercised', result.stdout)
            self.assertIn('LATER SUITE exercised', result.stdout)
            self.assertIn('SELFTEST exercised', result.stdout)
            self.assertIn('2 test files + ship-gate selftest; 1 failed', result.stdout)
            self.assertNotIn('HOST-ONLY-CHECK-RAN', result.stdout)
            (tests / 'a_test.py').write_text('print("REPAIRED SUITE exercised")\n')
            repaired = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root,
                                      capture_output=True, text=True)
            self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)

    def test_empty_inventory_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            (root / 'scripts').mkdir()
            (root / 'scripts/verify-unit.py').write_text(Path(__file__).with_name('verify-unit.py').read_text())
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            result = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('FAIL empty self-contained test inventory', result.stdout)


if __name__ == '__main__':
    unittest.main()

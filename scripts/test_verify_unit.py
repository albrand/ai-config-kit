"""Exercise test discovery and failure propagation through the stage CLI."""
from pathlib import Path
import json
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
            (root / 'scripts/verify-suites.json').write_text(json.dumps({
                'selftests': {str(gate.relative_to(root)): ['selftest']},
                'excluded': {str(host.relative_to(root)): 'host installation check'}}))
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            result = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('NESTED FAILURE exercised', result.stdout)
            self.assertIn('LATER SUITE exercised', result.stdout)
            self.assertIn('SELFTEST exercised', result.stdout)
            self.assertIn('2 test files + 1 CLI selftests; 1 failed', result.stdout)
            self.assertIn('failed suite: skillsets/new-skill/tests/a_test.py', result.stdout)
            self.assertNotIn('HOST-ONLY-CHECK-RAN', result.stdout)
            (tests / 'a_test.py').write_text('print("REPAIRED SUITE exercised")\n')
            repaired = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root,
                                      capture_output=True, text=True)
            self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)

    def test_unconventional_unittest_without_main_is_exercised(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            (root / 'scripts').mkdir()
            (root / 'scripts/verify-unit.py').write_text(Path(__file__).with_name('verify-unit.py').read_text())
            (root / 'checks').mkdir()
            audit = root / 'checks/audit.py'
            audit.write_text('from unittest import TestCase\nclass Audit(TestCase):\n    def test_outcome(self):\n        self.assertTrue(False)\n')
            (root / 'checks/test_anchor.py').write_text('print("anchor exercised")\n')
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            result = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('failed suite: checks/audit.py', result.stdout)
            self.assertIn('FAIL: test_outcome', result.stdout.rsplit('unit:', 1)[1])
            failure_log = root / '.verify/runs/unit-failures/checks/audit.py.log'
            self.assertIn('AssertionError', failure_log.read_text())
            self.assertIn('anchor exercised', result.stdout)
            audit.write_text(audit.read_text().replace('assertTrue(False)', 'assertTrue(True)'))
            repaired = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root, capture_output=True, text=True)
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


    def test_async_unittest_base_is_exercised(self):
        for module in ('unittest', 'unittest.async_case'):
            with self.subTest(module=module), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                subprocess.run(['git', 'init', '-q', tmp], check=True)
                (root / 'scripts').mkdir()
                (root / 'scripts/verify-unit.py').write_text(Path(__file__).with_name('verify-unit.py').read_text())
                (root / 'checks').mkdir()
                (root / 'checks/__init__.py').write_text('')
                audit = root / 'checks/audit.py'
                audit.write_text(f'from {module} import IsolatedAsyncioTestCase as AsyncCase\nclass Audit(AsyncCase):\n    async def test_outcome(self):\n        self.assertTrue(False)\n')
                (root / 'checks/test_anchor.py').write_text('pass\n')
                subprocess.run(['git', 'add', '.'], cwd=root, check=True)
                result = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('failed suite: checks/audit.py', result.stdout)
                audit.write_text(audit.read_text().replace('assertTrue(False)', 'assertTrue(True)'))
                repaired = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root, capture_output=True, text=True)
                self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)

    def test_imported_and_transitive_unittest_base_is_exercised(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            (root / 'scripts').mkdir()
            (root / 'scripts/verify-unit.py').write_text(Path(__file__).with_name('verify-unit.py').read_text())
            (root / 'checks').mkdir()
            (root / 'checks/__init__.py').write_text('')
            (root / 'checks/base.py').write_text('import unittest as ut\nclass BaseCase(ut.TestCase):\n    def test_anchor(self):\n        self.assertTrue(True)\n')
            (root / 'checks/middle.py').write_text('import checks.base as support\nclass Middle(support.BaseCase):\n    pass\n')
            audit = root / 'checks/audit.py'
            audit.write_text('from .middle import Middle as SharedCase\nclass LocalBase(SharedCase):\n    pass\nclass Audit(LocalBase):\n    def test_outcome(self):\n        self.assertTrue(False)\n')
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            result = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('failed suite: checks/audit.py', result.stdout)
            self.assertIn('PASS checks/middle.py', result.stdout)
            audit.write_text(audit.read_text().replace('assertTrue(False)', 'assertTrue(True)'))
            repaired = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root, capture_output=True, text=True)
            self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)


if __name__ == '__main__':
    unittest.main()

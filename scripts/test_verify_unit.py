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

    def test_inactive_main_call_does_not_skip_failing_suite(self):
        for entry in ('def launch():\n    unittest.main()\n', 'if False:\n    unittest.main()\n',
                      'def ignore(thunk):\n    pass\nignore(lambda: unittest.main())\n',
                      'print(unittest.main() if False else "inactive")\n',
                      'pending = lambda: unittest.main()\n',
                      'result = unittest.main() if False else None\n'):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                subprocess.run(['git', 'init', '-q', tmp], check=True)
                (root / 'scripts').mkdir()
                (root / 'scripts/verify-unit.py').write_text(Path(__file__).with_name('verify-unit.py').read_text())
                (root / 'checks').mkdir()
                audit = root / 'checks/audit.py'
                audit.write_text('import unittest\nclass Audit(unittest.TestCase):\n    def test_outcome(self):\n        self.assertTrue(False)\n' + entry)
                subprocess.run(['git', 'add', '.'], cwd=root, check=True)
                result = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('FAIL: test_outcome', result.stdout)
                audit.write_text(audit.read_text().replace('assertTrue(False)', 'assertTrue(True)'))
                repaired = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root, capture_output=True, text=True)
                self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)

    def test_main_guard_setup_and_import_alias_are_preserved(self):
        for guard, entry in ((guard, entry) for guard in ("__name__ == '__main__'", "'__main__' == __name__")
                             for entry in ('run_tests()', 'sys.exit(run_tests())', 'result = run_tests()',
                                           'result: object = run_tests()', 'result += run_tests()',
                                           '(result := run_tests())')):
            with self.subTest(guard=guard, entry=entry), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                subprocess.run(['git', 'init', '-q', tmp], check=True)
                (root / 'scripts').mkdir()
                (root / 'scripts/verify-unit.py').write_text(Path(__file__).with_name('verify-unit.py').read_text())
                (root / 'checks').mkdir()
                (root / 'checks/audit.py').write_text('import sys\nfrom unittest import TestCase, main as run_tests\n'
                    'class Audit(TestCase):\n    def test_outcome(self):\n        self.assertTrue(ready)\n'
                    f'if {guard}:\n    ready = True\n    result = 0\n    {entry}\n')
                subprocess.run(['git', 'add', '.'], cwd=root, check=True)
                result = subprocess.run([sys.executable, 'scripts/verify-unit.py'], cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('Ran 1 test', result.stdout)

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

    def test_native_suites_leave_the_unit_stage_and_run_only_with_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            (root / 'scripts').mkdir()
            (root / 'scripts/verify-unit.py').write_text(Path(__file__).with_name('verify-unit.py').read_text())
            (root / 'checks').mkdir()
            (root / 'checks/test_plain.py').write_text('print("PLAIN RAN")\n')
            (root / 'checks/test_sandboxed.py').write_text('print("NATIVE RAN")\nraise SystemExit(1)\n')
            (root / 'checks/gate.py').write_text('import sys\nprint("NATIVE SELFTEST", sys.argv[1:])\n')
            (root / 'scripts/verify-suites.json').write_text(json.dumps({
                'selftests': {'checks/gate.py': ['selftest']},
                'native': {'checks/test_sandboxed.py': 'applies its own sandbox', 'checks/gate.py': 'same'}}))
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            unit = subprocess.run([sys.executable, '-I', 'scripts/verify-unit.py'], cwd=root, capture_output=True, text=True)
            self.assertEqual(unit.returncode, 0, unit.stdout + unit.stderr)
            self.assertIn('PLAIN RAN', unit.stdout)
            self.assertNotIn('NATIVE', unit.stdout.replace('host-only check excluded', ''))
            self.assertIn('unit: 1 test files + 0 CLI selftests; 0 failed', unit.stdout)
            native = subprocess.run([sys.executable, '-I', 'scripts/verify-unit.py', '--native'], cwd=root,
                                    capture_output=True, text=True)
            self.assertEqual(native.returncode, 1, native.stdout + native.stderr)
            self.assertIn('NATIVE RAN', native.stdout)
            self.assertIn("NATIVE SELFTEST ['selftest']", native.stdout)
            self.assertNotIn('PLAIN RAN', native.stdout)
            self.assertIn('native: 1 test files + 1 CLI selftests; 1 failed', native.stdout)

    def test_native_lane_with_nothing_registered_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            (root / 'scripts').mkdir()
            (root / 'scripts/verify-unit.py').write_text(Path(__file__).with_name('verify-unit.py').read_text())
            (root / 'checks').mkdir()
            (root / 'checks/test_plain.py').write_text('pass\n')
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            result = subprocess.run([sys.executable, '-I', 'scripts/verify-unit.py', '--native'], cwd=root,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('FAIL no native suites are registered', result.stdout)

    def test_a_module_beside_the_helper_or_the_suites_cannot_replace_the_standard_library(self):
        # The runner pins scripts/verify-unit.py from the base branch; the PR can still add files around it. Run
        # isolated (as verify-unit.sh does), a scripts/json.py can't hijack the helper's own imports, and a tracked
        # unittest.py, which `python -m unittest` would run from the repo root in place of the real one, fails.
        for plant in ('scripts/json.py', 'scripts/subprocess.py', 'unittest.py', 'checks/unittest/__init__.py',
                      'sitecustomize.py'):
            with self.subTest(plant=plant), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                subprocess.run(['git', 'init', '-q', tmp], check=True)
                (root / 'scripts').mkdir()
                (root / 'scripts/verify-unit.py').write_text(Path(__file__).with_name('verify-unit.py').read_text())
                (root / 'checks').mkdir()
                (root / 'checks/test_audit.py').write_text(
                    'import unittest\nclass Audit(unittest.TestCase):\n    def test_outcome(self):\n'
                    '        self.assertTrue(False)\n')
                (root / plant).parent.mkdir(parents=True, exist_ok=True)
                (root / plant).write_text('import os\nprint("PLANT RAN")\nos._exit(0)\n')
                subprocess.run(['git', 'add', '.'], cwd=root, check=True)
                result = subprocess.run([sys.executable, '-I', 'scripts/verify-unit.py'], cwd=root,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertNotIn('PLANT RAN', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()

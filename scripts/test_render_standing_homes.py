from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("render-standing-homes.py")
SPEC = importlib.util.spec_from_file_location("render_standing_homes", SCRIPT)
RENDERER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RENDERER)


class InstallPreflightTests(unittest.TestCase):
    def make_homes(self, root: Path) -> tuple[dict[str, Path], dict[str, bytes], dict[str, str]]:
        targets = {}
        originals = {}
        hashes = {}
        for key in RENDERER.TARGETS:
            target = root / key / "AGENTS.md"
            target.parent.mkdir()
            original = f"original {key}\n".encode()
            target.write_bytes(original)
            targets[key] = target
            originals[key] = original
            hashes[key] = hashlib.sha256(original).hexdigest()
        return targets, originals, hashes

    def test_changed_target_refuses_before_any_backup_or_home_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets, originals, hashes = self.make_homes(root)
            changed = targets["opencode"]
            changed.write_bytes(b"changed after snapshot\n")
            invocation_state = {key: path.read_bytes() for key, path in targets.items()}
            outputs = {key: "replacement\n" for key in targets}

            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                RENDERER.install_homes(targets, outputs, hashes, stamp="fixed")

            self.assertEqual(invocation_state, {key: path.read_bytes() for key, path in targets.items()})
            self.assertEqual([], list(root.rglob("*.bak")))
            self.assertEqual(originals["claude"], targets["claude"].read_bytes())

    def test_existing_backup_is_preserved_and_new_unique_set_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets, originals, hashes = self.make_homes(root)
            occupied = targets["codex"].with_name("AGENTS.md.card21-fixed.bak")
            occupied.write_bytes(b"preserve this backup")
            outputs = {key: f"replacement {key}\n" for key in targets}

            backups = RENDERER.install_homes(targets, outputs, hashes, stamp="fixed")

            self.assertEqual(b"preserve this backup", occupied.read_bytes())
            for key, backup in backups.items():
                self.assertNotEqual(occupied, backup)
                self.assertEqual(originals[key], backup.read_bytes())
                self.assertEqual(outputs[key], targets[key].read_text(encoding="utf-8"))

    def test_replace_failure_rolls_back_replaced_homes_and_keeps_backups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets, originals, hashes = self.make_homes(root)
            outputs = {key: f"replacement {key}\n" for key in targets}
            real_replace = RENDERER.os.replace
            failed = False

            def fail_once(source, destination):
                nonlocal failed
                if Path(destination) == targets["codex"] and not failed:
                    failed = True
                    raise OSError("injected second-home replace failure")
                return real_replace(source, destination)

            with patch.object(RENDERER.os, "replace", side_effect=fail_once):
                with self.assertRaisesRegex(OSError, "injected second-home replace failure"):
                    RENDERER.install_homes(targets, outputs, hashes, stamp="rollback")

            self.assertEqual(originals, {key: path.read_bytes() for key, path in targets.items()})
            backups = list(root.rglob("*.bak"))
            self.assertEqual(4, len(backups))
            self.assertEqual(sorted(originals.values()), sorted(path.read_bytes() for path in backups))

    def test_fingerprint_manifest_rejects_duplicate_home_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hashes.md"
            row = "| Claude | " + "a" * 64 + " |\n"
            path.write_text(
                row + "| Codex | " + "b" * 64 + " |\n"
                + "| OpenCode | " + "c" * 64 + " |\n"
                + "| bb | " + "d" * 64 + " |\n" + row,
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "exactly one fingerprint per home"):
                RENDERER.load_expected_hashes(path)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("render-standing-homes.py")
SPEC = importlib.util.spec_from_file_location("render_standing_homes", SCRIPT)
RENDERER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RENDERER)


class CommittedSnapshotTests(unittest.TestCase):
    def test_committed_rendered_homes_match_the_renderer(self) -> None:
        # check-standing-rules fingerprints these files; a source edit must regenerate them.
        snapshots = RENDERER.ROOT / "proposals/card21/rendered-homes"
        for name, filename in RENDERER.NAMES.items():
            with self.subTest(home=name):
                self.assertEqual((snapshots / filename).read_text(encoding="utf-8"), RENDERER.rendered(name))


class InstallPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock_root = tempfile.TemporaryDirectory()
        self.lock_patch = patch.object(
            RENDERER.standing_home_lock,
            "LOCK_PATH",
            Path(self.lock_root.name) / "home-writers.lock",
        )
        self.lock_patch.start()

    def tearDown(self) -> None:
        self.lock_patch.stop()
        self.lock_root.cleanup()

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

    def test_rollback_preserves_concurrent_edit_and_reports_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets, originals, hashes = self.make_homes(root)
            outputs = {key: f"replacement {key}\n" for key in targets}
            concurrent_edit = b"newer edit from another writer\n"
            real_replace = RENDERER.os.replace
            failed = False

            def fail_after_concurrent_edit(source, destination):
                nonlocal failed
                if Path(destination) == targets["codex"] and not failed:
                    failed = True
                    targets["claude"].write_bytes(concurrent_edit)
                    raise OSError("injected second-home replace failure")
                return real_replace(source, destination)

            with patch.object(RENDERER.os, "replace", side_effect=fail_after_concurrent_edit):
                with self.assertRaisesRegex(RuntimeError, "rollback conflict.*target changed"):
                    RENDERER.install_homes(targets, outputs, hashes, stamp="concurrent")

            self.assertEqual(concurrent_edit, targets["claude"].read_bytes())
            self.assertEqual(originals["codex"], targets["codex"].read_bytes())
            backups = list(root.rglob("*.bak"))
            self.assertEqual(4, len(backups))
            self.assertIn(originals["claude"], [path.read_bytes() for path in backups])

    def test_exclusive_writer_protocol_closes_rollback_replace_race(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets, originals, hashes = self.make_homes(root)
            outputs = {key: f"replacement {key}\n" for key in targets}
            concurrent_edit = b"later sync edit after install lock releases\n"
            real_replace = RENDERER.os.replace
            real_rename = RENDERER.os.rename
            probe_done = threading.Event()
            writer_done = threading.Event()
            writers = []
            failures = []
            failed = False

            def later_sync_writer():
                try:
                    with self.assertRaises(BlockingIOError):
                        with RENDERER.standing_home_lock.exclusive_home_writer(blocking=False):
                            pass
                    probe_done.set()
                    with RENDERER.standing_home_lock.exclusive_home_writer():
                        targets["claude"].write_bytes(concurrent_edit)
                except BaseException as exc:
                    failures.append(exc)
                    probe_done.set()
                finally:
                    writer_done.set()

            def fail_second_replace(source, destination):
                nonlocal failed
                destination = Path(destination)
                if destination == targets["codex"] and not failed:
                    failed = True
                    raise OSError("injected later-home replacement failure")
                return real_replace(source, destination)

            def inject_before_rollback_rename(source, destination):
                if Path(source) == targets["claude"] and failed:
                    writer = threading.Thread(target=later_sync_writer)
                    writers.append(writer)
                    writer.start()
                    self.assertTrue(probe_done.wait(timeout=2), "writer lock probe did not complete")
                    self.assertEqual(outputs["claude"].encode(), targets["claude"].read_bytes())
                return real_rename(source, destination)

            with (
                patch.object(RENDERER.os, "replace", side_effect=fail_second_replace),
                patch.object(RENDERER.os, "rename", side_effect=inject_before_rollback_rename),
            ):
                with self.assertRaisesRegex(OSError, "injected later-home replacement failure"):
                    RENDERER.install_homes(targets, outputs, hashes, stamp="race")

            for writer in writers:
                writer.join(timeout=2)

            self.assertEqual([], failures)
            self.assertTrue(writer_done.is_set(), "later sync did not finish after lock release")
            self.assertEqual(concurrent_edit, targets["claude"].read_bytes())
            self.assertEqual(originals["codex"], targets["codex"].read_bytes())
            self.assertEqual(4, len(list(root.rglob("*.bak"))))

    def test_unlocked_edit_at_restore_link_boundary_survives_and_fails_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets, originals, hashes = self.make_homes(root)
            outputs = {key: f"replacement {key}\n" for key in targets}
            concurrent_edit = b"unlocked edit immediately before restore link\n"
            real_replace = RENDERER.os.replace
            real_link = RENDERER.os.link
            failed = False
            injected = False

            def fail_second_replace(source, destination):
                nonlocal failed
                if Path(destination) == targets["codex"] and not failed:
                    failed = True
                    raise OSError("injected second-home replace failure")
                return real_replace(source, destination)

            def write_before_restore_link(source, destination, **kwargs):
                nonlocal injected
                if Path(destination) == targets["claude"] and not injected:
                    injected = True
                    targets["claude"].write_bytes(concurrent_edit)
                return real_link(source, destination, **kwargs)

            stderr = io.StringIO()
            with (
                patch.object(RENDERER, "TARGETS", targets),
                patch.object(
                    RENDERER,
                    "install_from_sources",
                    side_effect=lambda: RENDERER.install_homes(targets, outputs, hashes, stamp="unlocked-link"),
                ),
                patch.object(RENDERER.os, "replace", side_effect=fail_second_replace),
                patch.object(RENDERER.os, "link", side_effect=write_before_restore_link),
                patch.object(sys, "argv", [str(SCRIPT), "--install"]),
                redirect_stderr(stderr),
            ):
                exit_code = RENDERER.main()

            self.assertTrue(injected, "unlocked edit was not injected at the restore-link boundary")
            self.assertEqual(2, exit_code)
            self.assertIn("rollback conflict", stderr.getvalue())
            self.assertIn("recreated the target", stderr.getvalue())
            self.assertEqual(concurrent_edit, targets["claude"].read_bytes())
            self.assertEqual(originals["codex"], targets["codex"].read_bytes())
            backups = list(root.rglob("*.bak"))
            self.assertEqual(4, len(backups))
            self.assertIn(originals["claude"], [backup.read_bytes() for backup in backups])
            recovery_dirs = list(root.rglob(".card21-rollback-*"))
            self.assertEqual(1, len(recovery_dirs))
            recovery_bytes = [path.read_bytes() for path in recovery_dirs[0].iterdir()]
            self.assertIn(outputs["claude"].encode(), recovery_bytes)
            self.assertIn(originals["claude"], recovery_bytes)

    def test_unlocked_edit_before_atomic_capture_is_reinserted_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets, originals, hashes = self.make_homes(root)
            outputs = {key: f"replacement {key}\n" for key in targets}
            concurrent_edit = b"unlocked edit immediately before atomic rename\n"
            real_replace = RENDERER.os.replace
            real_rename = RENDERER.os.rename
            failed = False
            injected = False

            def fail_second_replace(source, destination):
                nonlocal failed
                if Path(destination) == targets["codex"] and not failed:
                    failed = True
                    raise OSError("injected second-home replace failure")
                return real_replace(source, destination)

            def write_before_capture_rename(source, destination):
                nonlocal injected
                if Path(source) == targets["claude"] and failed and not injected:
                    injected = True
                    targets["claude"].write_bytes(concurrent_edit)
                return real_rename(source, destination)

            with (
                patch.object(RENDERER.os, "replace", side_effect=fail_second_replace),
                patch.object(RENDERER.os, "rename", side_effect=write_before_capture_rename),
            ):
                with self.assertRaisesRegex(RuntimeError, "rollback conflict.*target changed"):
                    RENDERER.install_homes(targets, outputs, hashes, stamp="unlocked-rename")

            self.assertTrue(injected, "unlocked edit was not injected before atomic capture")
            self.assertEqual(concurrent_edit, targets["claude"].read_bytes())
            self.assertEqual(originals["codex"], targets["codex"].read_bytes())
            backups = list(root.rglob("*.bak"))
            self.assertEqual(4, len(backups))
            self.assertIn(originals["claude"], [backup.read_bytes() for backup in backups])

    def test_open_descriptor_edit_is_retained_and_reported_as_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets, originals, hashes = self.make_homes(root)
            outputs = {key: f"replacement {key}\n" for key in targets}
            descriptor_edit = b"edit written through pre-rename descriptor\n"
            real_replace = RENDERER.os.replace
            real_rename = RENDERER.os.rename
            real_link = RENDERER.os.link
            descriptor = None
            failed = False
            edited = False

            def fail_second_replace(source, destination):
                nonlocal failed
                if Path(destination) == targets["codex"] and not failed:
                    failed = True
                    raise OSError("injected second-home replace failure")
                return real_replace(source, destination)

            def open_before_atomic_capture(source, destination):
                nonlocal descriptor
                if Path(source) == targets["claude"] and failed and descriptor is None:
                    descriptor = os.open(source, os.O_RDWR)
                return real_rename(source, destination)

            def edit_before_restore_link(source, destination, **kwargs):
                nonlocal descriptor, edited
                if Path(destination) == targets["claude"] and descriptor is not None:
                    open_fd = descriptor
                    os.lseek(open_fd, 0, os.SEEK_SET)
                    os.write(open_fd, descriptor_edit)
                    os.ftruncate(open_fd, len(descriptor_edit))
                    edited = True
                    try:
                        return real_link(source, destination, **kwargs)
                    finally:
                        os.close(open_fd)
                        descriptor = None
                return real_link(source, destination, **kwargs)

            stderr = io.StringIO()
            try:
                with (
                    patch.object(RENDERER, "TARGETS", targets),
                    patch.object(
                        RENDERER,
                        "install_from_sources",
                        side_effect=lambda: RENDERER.install_homes(targets, outputs, hashes, stamp="open-fd"),
                    ),
                    patch.object(RENDERER.os, "replace", side_effect=fail_second_replace),
                    patch.object(RENDERER.os, "rename", side_effect=open_before_atomic_capture),
                    patch.object(RENDERER.os, "link", side_effect=edit_before_restore_link),
                    patch.object(sys, "argv", [str(SCRIPT), "--install"]),
                    redirect_stderr(stderr),
                ):
                    exit_code = RENDERER.main()
            finally:
                if descriptor is not None:
                    os.close(descriptor)

            self.assertTrue(edited, "descriptor edit did not run at the restore-link boundary")
            self.assertEqual(2, exit_code)
            self.assertIn("rollback conflict", stderr.getvalue())
            self.assertIn("captured inode retained at", stderr.getvalue())
            self.assertEqual(originals["claude"], targets["claude"].read_bytes())
            self.assertEqual(originals["codex"], targets["codex"].read_bytes())
            backups = list(root.rglob("*.bak"))
            self.assertEqual(4, len(backups))
            self.assertIn(originals["claude"], [backup.read_bytes() for backup in backups])
            captured = list(root.rglob("captured"))
            self.assertEqual(1, len(captured))
            self.assertEqual(descriptor_edit, captured[0].read_bytes())

    def test_rollback_directory_failure_isolated_and_staged_files_are_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets, originals, hashes = self.make_homes(root)
            outputs = {key: f"replacement {key}\n" for key in targets}
            real_replace = RENDERER.os.replace
            real_mkdtemp = RENDERER.tempfile.mkdtemp
            real_named_temporary_file = RENDERER.tempfile.NamedTemporaryFile
            failed = False
            rollback_dirs = []
            staged_paths = []

            def fail_third_replace(source, destination):
                nonlocal failed
                if Path(destination) == targets["opencode"] and not failed:
                    failed = True
                    raise OSError("injected third-home replace failure")
                return real_replace(source, destination)

            def fail_first_recovery_dir(*args, **kwargs):
                rollback_dirs.append(Path(kwargs["dir"]))
                if len(rollback_dirs) == 1:
                    raise OSError("injected recovery directory ENOSPC")
                return real_mkdtemp(*args, **kwargs)

            def track_temporary_file(*args, **kwargs):
                tmp = real_named_temporary_file(*args, **kwargs)
                staged_paths.append(Path(tmp.name))
                return tmp

            stderr = io.StringIO()
            with (
                patch.object(RENDERER, "TARGETS", targets),
                patch.object(
                    RENDERER,
                    "install_from_sources",
                    side_effect=lambda: RENDERER.install_homes(targets, outputs, hashes, stamp="rollback-enospc"),
                ),
                patch.object(RENDERER.os, "replace", side_effect=fail_third_replace),
                patch.object(RENDERER.tempfile, "mkdtemp", side_effect=fail_first_recovery_dir),
                patch.object(RENDERER.tempfile, "NamedTemporaryFile", side_effect=track_temporary_file),
                patch.object(sys, "argv", [str(SCRIPT), "--install"]),
                redirect_stderr(stderr),
            ):
                exit_code = RENDERER.main()

            self.assertEqual(2, exit_code)
            self.assertIn("injected recovery directory ENOSPC", stderr.getvalue())
            self.assertEqual([targets["codex"].parent, targets["claude"].parent], rollback_dirs)
            self.assertEqual(originals["claude"], targets["claude"].read_bytes())
            self.assertEqual(outputs["codex"].encode(), targets["codex"].read_bytes())
            self.assertEqual(originals["opencode"], targets["opencode"].read_bytes())
            self.assertEqual(originals["bb"], targets["bb"].read_bytes())
            self.assertTrue(staged_paths)
            self.assertTrue(all(not path.exists() for path in staged_paths))

    def make_install_source_repo(self, root: Path) -> Path:
        repo = root / "repo"
        remote = root / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        subprocess.run(["git", "init", "--initial-branch=main", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Card 21 test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "card21-test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(remote)], check=True)
        for source in RENDERER.INSTALL_SOURCE_PATHS:
            path = repo / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"initial source: {source}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", *RENDERER.INSTALL_SOURCE_PATHS], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "Initial main install sources"], check=True)
        subprocess.run(["git", "-C", str(repo), "push", "-qu", "origin", "main"], check=True)
        return repo

    def test_install_source_guard_rejects_unmerged_and_accepts_fetched_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_install_source_repo(Path(directory))
            changed = repo / "GLOBAL_AGENTS.md"
            changed.write_text("candidate source not yet on main\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "feat/card21"], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "GLOBAL_AGENTS.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "Candidate instructions"], check=True)

            with self.assertRaisesRegex(ValueError, "differs from pinned origin/main"):
                RENDERER.assert_install_sources_in_origin_main(RENDERER.capture_install_sources(repo), repo)

            subprocess.run(["git", "-C", str(repo), "push", "origin", "HEAD:main"], check=True, capture_output=True)
            RENDERER.assert_install_sources_in_origin_main(RENDERER.capture_install_sources(repo), repo)

    def test_fetch_refusal_does_not_echo_remote_credentials(self) -> None:
        fetch_args = ["git", "fetch", "origin", "main"]
        result = subprocess.CompletedProcess(
            fetch_args,
            128,
            stdout="could not reach https://user:secret@example.invalid/repo.git",
            stderr="fatal: unable to access 'https://user:secret@example.invalid/repo.git': denied",
        )

        with patch.object(RENDERER.subprocess, "run", return_value=result) as run:
            with self.assertRaisesRegex(ValueError, "git fetch origin/main failed with exit code 128") as raised:
                RENDERER.assert_install_sources_in_origin_main(
                    {source: b"" for source in RENDERER.INSTALL_SOURCE_PATHS},
                    Path("/tmp/not-a-repo"),
                )

        self.assertEqual(
            [
                "git", "-C", "/tmp/not-a-repo", "fetch", "--no-tags", "origin",
                "main:refs/remotes/origin/main",
            ],
            run.call_args.args[0],
        )
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("example.invalid", str(raised.exception))

    def test_main_install_rejects_candidate_render_if_source_restores_before_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_install_source_repo(root)
            targets = {key: root / "homes" / key / "AGENTS.md" for key in RENDERER.TARGETS}
            for target in targets.values():
                target.parent.mkdir(parents=True)
                target.write_text("original live home\n", encoding="utf-8")

            # Make the fixture renderer inputs valid, then pin matching live-home fingerprints.
            (repo / "GLOBAL_AGENTS.md").write_text("main instructions\n", encoding="utf-8")
            (repo / "proposals/card21/hard-rules.md").write_text("hard rules\n", encoding="utf-8")
            (repo / "scripts/typed-decisions-sync.py").write_text(
                'GLOBAL_BLOCK = "typed rules"\n', encoding="utf-8"
            )
            for name in ("claude", "codex", "opencode", "bb"):
                (repo / f"proposals/card21/overlays/{name}.md").write_text(
                    f"overlay {name}\n", encoding="utf-8"
                )
            candidate_outputs = {
                key: RENDERER.rendered(key, RENDERER.capture_install_sources(repo))
                for key in targets
            }
            manifest_path = repo / "proposals/card21/live-home-hashes.md"
            manifest_path.write_text(
                "\n".join(
                    f"| {RENDERER.HASH_NAMES[key]} | `{hashlib.sha256(b'original live home\\n').hexdigest()}` |"
                    for key in targets
                ) + "\n",
                encoding="utf-8",
            )
            base_global = (repo / "GLOBAL_AGENTS.md").read_bytes()
            subprocess.run(["git", "-C", str(repo), "add", *RENDERER.INSTALL_SOURCE_PATHS], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "Valid main render sources"], check=True)
            subprocess.run(["git", "-C", str(repo), "push", "-qu", "origin", "main"], check=True)
            (repo / "GLOBAL_AGENTS.md").write_text("candidate instructions\n", encoding="utf-8")

            real_guard = RENDERER.assert_install_sources_in_origin_main
            real_rendered = RENDERER.rendered
            rendered_candidate = []

            def record_render(name, sources=None):
                result = real_rendered(name, sources)
                if sources is not None and sources["GLOBAL_AGENTS.md"] == b"candidate instructions\n":
                    rendered_candidate.append((name, result))
                return result

            def restore_before_guard(snapshot, repo_root):
                (repo_root / "GLOBAL_AGENTS.md").write_bytes(base_global)
                return real_guard(snapshot, repo_root)

            with (
                patch.object(RENDERER, "ROOT", repo),
                patch.object(RENDERER, "TARGETS", targets),
                patch.object(RENDERER, "rendered", side_effect=record_render),
                patch.object(RENDERER, "assert_install_sources_in_origin_main", side_effect=restore_before_guard),
                patch.object(sys, "argv", [str(SCRIPT), "--install"]),
            ):
                self.assertEqual(2, RENDERER.main())

            self.assertTrue(rendered_candidate, "complete entry point did not render candidate bytes")
            self.assertIn("candidate instructions", dict(rendered_candidate)["bb"])
            self.assertNotEqual(candidate_outputs["claude"], targets["claude"].read_text(encoding="utf-8"))
            self.assertTrue(all(path.read_text(encoding="utf-8") == "original live home\n" for path in targets.values()))
            self.assertEqual([], list(root.rglob("*.bak")))

    def test_check_and_render_modes_do_not_require_sources_on_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = {key: root / key / "AGENTS.md" for key in RENDERER.TARGETS}
            outputs = {key: RENDERER.rendered(key) for key in targets}
            for key, target in targets.items():
                target.parent.mkdir()
                target.write_text(outputs[key], encoding="utf-8")
            output_dir = root / "rendered"

            with (
                patch.object(RENDERER, "TARGETS", targets),
                patch.object(RENDERER, "assert_install_sources_in_origin_main", side_effect=AssertionError("main gate called")),
                patch.object(sys, "argv", [str(SCRIPT), "--check"]),
            ):
                self.assertEqual(0, RENDERER.main())

            with (
                patch.object(RENDERER, "assert_install_sources_in_origin_main", side_effect=AssertionError("main gate called")),
                patch.object(sys, "argv", [str(SCRIPT), "--output-dir", str(output_dir)]),
            ):
                self.assertEqual(0, RENDERER.main())
            self.assertEqual(set(RENDERER.NAMES.values()), {path.name for path in output_dir.iterdir()})

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

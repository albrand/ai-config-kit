#!/usr/bin/env python3
"""Offline tests for the native-agent-surfaces installer.

No network, no third-party dependencies, no writes to the real home directory.
Each test points XDG_CONFIG_HOME / XDG_DATA_HOME / CODEX_HOME at a temp tree and
runs the installer against the real (read-only) skillset source root.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import install  # noqa: E402

SOURCE_ROOT = SCRIPT_DIR.parent  # skillsets/native-agent-surfaces/


class _Env(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._saved_env = {
            k: os.environ.get(k) for k in
            ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "CODEX_HOME", "PATH")
        }
        self.tmp = tempfile.mkdtemp(prefix="nas-install-test-")
        self.config_home = Path(self.tmp) / "config"
        self.data_home = Path(self.tmp) / "data"
        self.codex_home = Path(self.tmp) / "codex"
        for d in (self.config_home, self.data_home, self.codex_home):
            d.mkdir(parents=True, exist_ok=True)
        os.environ["XDG_CONFIG_HOME"] = str(self.config_home)
        os.environ["XDG_DATA_HOME"] = str(self.data_home)
        os.environ["CODEX_HOME"] = str(self.codex_home)

    def tearDown(self):
        os.chdir(self._cwd)
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers -------------------------------------------------------------- #
    def run_install(self, *extra, expect=0):
        return self._run(["install", *extra], expect=expect)

    def run_uninstall(self, *extra, expect=0):
        return self._run(["uninstall", *extra], expect=expect)

    def _run(self, argv, expect):
        rc = install.main(argv)
        if expect is not None:
            self.assertEqual(rc, expect, f"expected rc {expect} for {argv}, got {rc}")
        return rc

    def set_pref(self, mode=None, schema_version=install.PREF_SCHEMA_VERSION,
                 extra_body=None, raw=None):
        path = install.pref_file(self.config_home)
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
            return
        body = {"schema_version": schema_version,
                install.PREF_KEY: {"mode": mode}}
        if extra_body:
            body.update(extra_body)
        path.write_text(json.dumps(body), encoding="utf-8")

    def receipt(self):
        return install.read_receipt(self.config_home)

    def source_hashes(self):
        manifest = install.load_manifest(SOURCE_ROOT)
        return {
            "canonical": {rel: install.sha256_file(src) for rel, src in
                          install.collect_knowledge_payload(SOURCE_ROOT, manifest)},
            "codex_adapter": {rel: install.sha256_file(src) for rel, src in
                              install.collect_codex_payload(SOURCE_ROOT, manifest)},
        }

    def canon_root(self):
        return install.canonical_target(self.data_home)

    def adapter_root(self):
        return install.codex_adapter_target(self.codex_home)


class NoPreferenceTest(_Env):
    def test_install_without_preference_fails_closed(self):
        rc = self.run_install(expect=2)
        self.assertFalse(install.pref_file(self.config_home).exists())
        self.assertIsNone(self.receipt())
        self.assertFalse(self.canon_root().exists())


class EnabledIdempotenceParityTest(_Env):
    def test_enabled_installs_and_is_idempotent_with_parity(self):
        self.run_install("--mode", "enabled", expect=0)
        rec = self.receipt()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["mode"], "enabled")
        expected = self.source_hashes()

        # parity: every installed file hash equals the source hash
        for key in ("canonical", "codex_adapter"):
            files = rec["targets"][key]["files"]
            for rel, meta in files.items():
                self.assertEqual(meta["hash"], expected[key][rel], f"{key}/{rel} parity")

        self.assertIn("bundle-manifest.json", expected["canonical"])
        self.assertNotIn("SKILL.md", expected["canonical"])
        self.assertIn("SKILL.md", expected["codex_adapter"])

        # source_tree_hash covers the same payload
        self.assertEqual(
            rec["source_tree_hash"],
            install.tree_hash(
                [(f"knowledge/{rel}", digest)
                 for rel, digest in expected["canonical"].items()]
                + [(f"adapters/codex/{rel}", digest)
                   for rel, digest in expected["codex_adapter"].items()]
            ),
        )

        # capture mtimes; second run must not churn them
        root = self.canon_root()
        mt_before = {rel: (root / rel).stat().st_mtime
                     for rel in expected["canonical"]}
        self.run_install("--mode", "enabled", expect=0)
        mt_after = {rel: (root / rel).stat().st_mtime
                    for rel in expected["canonical"]}
        self.assertEqual(mt_before, mt_after, "idempotent run churned mtimes")

        # executables remain executable
        for rel in install.load_manifest(SOURCE_ROOT).get("executable", []):
            self.assertTrue(os.access(root / rel, os.X_OK), f"{rel} not executable")


class DisabledNoDeleteTest(_Env):
    def test_disabled_persists_and_does_not_delete(self):
        self.run_install("--mode", "enabled", expect=0)
        self.assertTrue(self.canon_root().exists())
        self.run_install("--mode", "disabled", expect=0)
        # nothing removed by disabled
        self.assertTrue(self.canon_root().exists())
        self.assertTrue((self.adapter_root()).exists())
        # preference persisted as disabled
        self.assertEqual(install.read_preference(self.config_home), "disabled")

    def test_disabled_from_clean_persists_only(self):
        self.run_install("--mode", "disabled", expect=0)
        self.assertFalse(self.canon_root().exists())
        self.assertIsNone(self.receipt())
        self.assertEqual(install.read_preference(self.config_home), "disabled")


class CorruptPreferenceTest(_Env):
    def test_invalid_json_fails_closed(self):
        self.set_pref(raw="{ not valid json")
        self.run_install(expect=2)

    def test_wrong_schema_fails_closed(self):
        self.set_pref("enabled", schema_version=999)
        self.run_install(expect=2)

    def test_unknown_mode_fails_closed(self):
        self.set_pref("please")
        self.run_install(expect=2)


class ConflictBackupTest(_Env):
    def _seed_conflict(self):
        root = self.canon_root()
        (root / "README.md").parent.mkdir(parents=True, exist_ok=True)
        (root / "README.md").write_text("OPERATOR CUSTOM CONTENT", encoding="utf-8")

    def test_conflict_blocks_without_backup_flag(self):
        self._seed_conflict()
        self.run_install("--mode", "enabled", expect=2)
        self.assertEqual(
            (self.canon_root() / "README.md").read_text(encoding="utf-8"),
            "OPERATOR CUSTOM CONTENT",
        )

    def test_conflict_backed_up_then_installed(self):
        self._seed_conflict()
        self.run_install("--mode", "enabled", "--backup-conflicts", expect=0)
        rec = self.receipt()
        expected = self.source_hashes()
        self.assertEqual(
            rec["targets"]["canonical"]["files"]["README.md"]["hash"],
            expected["canonical"]["README.md"],
        )
        backups = [p for p in self.canon_root().parent.iterdir()
                   if p.name.startswith("native-agent-surfaces.bak.")]
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "README.md").read_text(encoding="utf-8"),
                         "OPERATOR CUSTOM CONTENT")


class AutoModeTest(_Env):
    def test_auto_skips_when_headless(self):
        # Under unittest capture, stdin/stdout are not TTYs.
        self.run_install("--mode", "auto", expect=0)
        self.assertIsNone(self.receipt())
        self.assertFalse(self.canon_root().exists())
        self.assertEqual(install.read_preference(self.config_home), "auto")

    def test_auto_installs_when_tty_and_host_present(self):
        original_tty = install.tty_check
        install.tty_check = lambda: True
        bin_dir = Path(self.tmp) / "fakebin"
        bin_dir.mkdir()
        (bin_dir / "tmux").write_text("#!/bin/sh\n", encoding="utf-8")
        os.chmod(bin_dir / "tmux", 0o755)
        os.environ["PATH"] = str(bin_dir) + os.pathsep + (self._saved_env["PATH"] or "")
        try:
            self.run_install("--mode", "auto", expect=0)
        finally:
            install.tty_check = original_tty
        rec = self.receipt()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["mode"], "auto")
        self.assertTrue(rec.get("audit_reason", "").startswith("auto: installed"))


class UninstallOwnershipTest(_Env):
    def test_uninstall_blocks_on_modified_file_then_succeeds(self):
        self.run_install("--mode", "enabled", expect=0)
        target = self.canon_root() / "README.md"
        self.assertTrue(target.exists())
        # tamper with a managed file
        target.write_bytes(target.read_bytes() + b"\nEDITED\n")
        self.run_uninstall(expect=2)
        # still present (blocked)
        self.assertTrue(target.exists())
        self.assertIsNotNone(self.receipt())

        # restore to receipt hash, then uninstall succeeds
        rec = self.receipt()
        src_hash = rec["targets"]["canonical"]["files"]["README.md"]["hash"]
        # regenerate the managed content from source
        manifest = install.load_manifest(SOURCE_ROOT)
        payload = dict(install.collect_knowledge_payload(SOURCE_ROOT, manifest))
        target.write_bytes(payload["README.md"].read_bytes())
        self.assertEqual(install.sha256_file(target), src_hash)

        self.run_uninstall(expect=0)
        self.assertFalse(target.exists())
        self.assertFalse(install.receipt_file(self.config_home).exists())
        self.assertEqual(install.read_preference(self.config_home), "disabled")

    def test_uninstall_no_receipt_persists_disabled(self):
        self.run_uninstall(expect=0)
        self.assertEqual(install.read_preference(self.config_home), "disabled")

    def test_uninstall_rejects_receipt_root_outside_configured_target(self):
        self.run_install("--mode", "enabled", expect=0)
        rec = self.receipt()
        sentinel = Path(self.tmp) / "outside" / "README.md"
        sentinel.parent.mkdir()
        sentinel.write_text("do not remove", encoding="utf-8")
        rec["targets"]["canonical"]["root"] = str(sentinel.parent)
        install._atomic_write_json(install.receipt_file(self.config_home), rec)

        self.run_uninstall(expect=2)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "do not remove")

    def test_uninstall_rejects_escaping_relative_path(self):
        self.run_install("--mode", "enabled", expect=0)
        rec = self.receipt()
        meta = next(iter(rec["targets"]["canonical"]["files"].values()))
        rec["targets"]["canonical"]["files"] = {"../outside": meta}
        install._atomic_write_json(install.receipt_file(self.config_home), rec)

        self.run_uninstall(expect=2)


class PreferenceAtomicityTest(_Env):
    def test_unrelated_keys_preserved(self):
        path = install.pref_file(self.config_home)
        path.parent.mkdir(parents=True, exist_ok=True)
        seed = {
            "schema_version": install.PREF_SCHEMA_VERSION,
            "another_tool": {"mode": "enabled"},
            "operator_note": "keep me",
            install.PREF_KEY: {"mode": "disabled"},
        }
        path.write_text(json.dumps(seed), encoding="utf-8")
        self.run_install("--mode", "enabled", expect=0)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["another_tool"], {"mode": "enabled"})
        self.assertEqual(data["operator_note"], "keep me")
        self.assertEqual(data[install.PREF_KEY]["mode"], "enabled")

    def test_explicit_mode_does_not_replace_corrupt_preferences(self):
        path = install.pref_file(self.config_home)
        path.parent.mkdir(parents=True, exist_ok=True)
        corrupt = b"{ not valid json"
        path.write_bytes(corrupt)

        self.run_install("--mode", "enabled", expect=2)
        self.assertEqual(path.read_bytes(), corrupt)


class ReceiptNoEnvTest(_Env):
    def test_receipt_records_no_env_values(self):
        os.environ["NASTEST_SECRET"] = "supersecret-value"
        try:
            self.run_install("--mode", "enabled", expect=0)
        finally:
            del os.environ["NASTEST_SECRET"]
        raw = install.receipt_file(self.config_home).read_text(encoding="utf-8")
        self.assertNotIn("supersecret-value", raw)
        self.assertNotIn("NASTEST_SECRET", raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)

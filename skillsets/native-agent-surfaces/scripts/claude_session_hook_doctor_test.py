#!/usr/bin/env python3
"""Offline fixture tests for the Claude session-start hook doctor.

No network, no third-party dependencies, no real home writes, no real plugin
execution. Plugin trees and process listings are built in a temp dir or injected
directly. Run from the ai-config-kit source tree:

    python3 skillsets/native-agent-surfaces/scripts/claude_session_hook_doctor_test.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent / "codex" / "native-agent-surface"
SOURCE_ROOT = SCRIPT_DIR.parent  # skillsets/native-agent-surfaces/

# The doctor filename has hyphens, so load it by path.
_spec = importlib.util.spec_from_file_location(
    "claude_session_hook_doctor",
    SKILL_DIR / "scripts" / "claude-session-hook-doctor.py")
assert _spec is not None and _spec.loader is not None
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)

# Installer, for manifest/receipt parity checks.
sys.path.insert(0, str(SCRIPT_DIR))
import install  # noqa: E402


def _write_hooks(plugin_dir: Path, obj) -> None:
    hf = plugin_dir / "hooks" / "hooks.json"
    hf.parent.mkdir(parents=True, exist_ok=True)
    hf.write_text(json.dumps(obj), encoding="utf-8")


class PluginValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doctor-plugin-"))
        self.sh = os.environ.get("SH") or __import__("shutil").which("sh") or "/bin/sh"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plugin(self, name: str, installPath: str | None = None,
                enabled: bool = True) -> dict:
        return {"id": name, "version": "1.0", "enabled": enabled,
                "installPath": installPath or str(self.tmp / name)}

    def test_clean_pass_healthy(self):
        root = self.tmp / "good"
        (root / "scripts").mkdir(parents=True)
        target = root / "scripts" / "run.sh"
        target.write_text("#!/bin/sh\necho hi\n")
        _write_hooks(root, {"hooks": {doctor.SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command", "command": f"{self.sh} {target}",
                 "timeout": 5}]}]}})
        rep = doctor.validate_plugin(self._plugin("good", str(root)))
        self.assertEqual(rep["status"], "healthy", rep["issues"])
        self.assertEqual(rep["session_start"]["count"], 1)
        self.assertEqual(rep["session_start"]["duplicates"], [])

    def test_plugin_root_variable_resolves(self):
        root = self.tmp / "pluginroot"
        target = root / "hooks" / "start.mjs"
        target.parent.mkdir(parents=True)
        target.write_text("// fixture\n")
        _write_hooks(root, {"hooks": {doctor.SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command",
                 "command": 'node "${CLAUDE_PLUGIN_ROOT}/hooks/start.mjs"'}]}]}})
        rep = doctor.validate_plugin(self._plugin("pluginroot", str(root)))
        self.assertEqual(rep["status"], "healthy", rep["issues"])

    def test_plugin_root_variable_missing_target_is_error(self):
        root = self.tmp / "pluginroot-missing"
        _write_hooks(root, {"hooks": {doctor.SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command",
                 "command": 'node "${CLAUDE_PLUGIN_ROOT}/hooks/missing.mjs"'}]}]}})
        rep = doctor.validate_plugin(
            self._plugin("pluginroot-missing", str(root))
        )
        codes = {i["code"] for i in rep["issues"]}
        self.assertIn("target-missing", codes)
        self.assertEqual(rep["status"], "error")

    def test_missing_plugin_root_is_error(self):
        rep = doctor.validate_plugin(
            self._plugin("ghost", str(self.tmp / "does-not-exist")))
        self.assertEqual(rep["status"], "error")
        codes = {i["code"] for i in rep["issues"]}
        self.assertIn("install-path-missing", codes)

    def test_missing_target_is_error(self):
        root = self.tmp / "badtarget"
        _write_hooks(root, {"hooks": {doctor.SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command",
                 "command": f"{self.sh} {root}/scripts/missing.sh"}]}]}})
        rep = doctor.validate_plugin(self._plugin("badtarget", str(root)))
        self.assertEqual(rep["status"], "error")
        codes = {i["code"] for i in rep["issues"]}
        self.assertIn("target-missing", codes)

    def test_missing_runtime_is_error(self):
        root = self.tmp / "badrt"
        _write_hooks(root, {"hooks": {doctor.SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command",
                 "command": "definitely-not-a-real-binary-xyz arg"}]}]}})
        rep = doctor.validate_plugin(self._plugin("badrt", str(root)))
        self.assertEqual(rep["status"], "error")
        codes = {i["code"] for i in rep["issues"]}
        self.assertIn("runtime-missing", codes)

    def test_runtime_directory_is_error(self):
        _runtime, issue = doctor._check_runtime([str(self.tmp)])
        self.assertIsNotNone(issue)
        self.assertEqual(issue["code"], "runtime-missing")

    def test_duplicate_session_start_command_is_warning(self):
        root = self.tmp / "dup"
        cmd = '"${CMUX_CLAUDE_HOOK_CMUX_BIN:-cmux}" hooks claude session-start'
        _write_hooks(root, {"hooks": {doctor.SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command", "command": cmd},
                {"type": "command", "command": cmd}]}]}})
        rep = doctor.validate_plugin(self._plugin("dup", str(root)))
        fingerprints = rep["session_start"]["duplicates"]
        self.assertEqual(len(fingerprints), 1)
        self.assertNotIn(cmd, json.dumps(rep))
        codes = {i["code"] for i in rep["issues"]}
        self.assertIn("duplicate-command", codes)
        self.assertEqual(rep["status"], "warning")

    def test_disabled_plugin_ignored(self):
        # Disabled plugin points at a nonexistent root yet stays "skipped".
        rep = doctor.validate_plugin(
            self._plugin("off", str(self.tmp / "nope"), enabled=False))
        self.assertEqual(rep["status"], "skipped")
        self.assertEqual(rep["issues"], [])

    def test_malformed_hooks_json_is_error(self):
        root = self.tmp / "ugly"
        (root / "hooks").mkdir(parents=True)
        (root / "hooks" / "hooks.json").write_text("{not valid json")
        rep = doctor.validate_plugin(self._plugin("ugly", str(root)))
        self.assertEqual(rep["status"], "error")
        codes = {i["code"] for i in rep["issues"]}
        self.assertIn("hooks-malformed", codes)

    def test_mcp_only_plugin_without_hooks_is_healthy(self):
        root = self.tmp / "mcp"
        root.mkdir(parents=True)
        rep = doctor.validate_plugin(self._plugin("mcp", str(root)))
        self.assertEqual(rep["status"], "healthy")
        self.assertFalse(rep["hooks_present"])

    def test_relative_install_path_is_error(self):
        rep = doctor.validate_plugin(
            {"id": "rel", "enabled": True, "installPath": "relative/path"})
        self.assertEqual(rep["status"], "error")
        codes = {i["code"] for i in rep["issues"]}
        self.assertIn("install-path-relative", codes)

    def test_target_escape_is_error(self):
        root = self.tmp / "esc"
        _write_hooks(root, {"hooks": {doctor.SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command",
                 "command": f"{self.sh} {root}/../../etc/hosts"}]}]}})
        rep = doctor.validate_plugin(self._plugin("esc", str(root)))
        codes = {i["code"] for i in rep["issues"]}
        # /etc/hosts resolves outside the plugin root -> escape or missing.
        self.assertTrue(codes & {"target-escape", "target-missing"}, codes)

    def test_env_referenced_runtime_is_warning_not_error(self):
        root = self.tmp / "envref"
        cmd = '"${CMUX_CLAUDE_HOOK_CMUX_BIN:-cmux}" hooks claude session-start'
        _write_hooks(root, {"hooks": {doctor.SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command", "command": cmd}]}]}})
        rep = doctor.validate_plugin(self._plugin("envref", str(root)))
        codes = {i["code"] for i in rep["issues"]}
        self.assertIn("runtime-env-ref", codes)
        self.assertNotIn("runtime-missing", codes)

    def test_shell_wrapper_fails_closed(self):
        root = self.tmp / "shell"
        _write_hooks(root, {"hooks": {doctor.SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command",
                 "command": (
                     'sh -c \'node "${CLAUDE_PLUGIN_ROOT}/hooks/missing.mjs"\''
                 )}]}]}})
        rep = doctor.validate_plugin(self._plugin("shell", str(root)))
        codes = {i["code"] for i in rep["issues"]}
        self.assertIn("shell-wrapper-unverified", codes)
        self.assertEqual(rep["status"], "error")


class ProcessProbeTests(unittest.TestCase):
    def _runner(self, pid: int, lstart: str, command: str):
        text = f"{pid} {lstart} {command}\n"

        def _r(_timeout):
            return 0, text, ""
        return _r

    def test_stale_process_triggers_restart_advisory(self):
        # Artifact mtime in the future relative to a 2012 process start.
        manifest = {"claude:/home/me/claude": 1900000000.0}  # ~ year 2030
        runner = self._runner(4242, "Mon Jan 02 00:00:00 2012",
                              "/home/me/claude --resume abc")
        procs, warns = doctor.probe_processes(
            "/home/me/claude", manifest, 5, ps_runner=runner)
        self.assertEqual(len(procs), 1)
        self.assertTrue(procs[0]["restart_required"])
        self.assertEqual(warns, [])

    def test_unverified_process_identity_is_suspected_not_required(self):
        manifest = {"plugin:/tmp/hooks.json": 1900000000.0}
        runner = self._runner(
            4243,
            "Mon Jan 02 00:00:00 2012",
            "/different/install/claude --resume abc",
        )
        procs, warns = doctor.probe_processes(
            "/home/me/claude", manifest, 5, ps_runner=runner
        )
        self.assertFalse(procs[0]["restart_required"])
        self.assertTrue(procs[0]["restart_suspected"])
        self.assertFalse(procs[0]["identity_verified"])
        self.assertTrue(
            any(w["code"] == "process-identity-unverified" for w in warns)
        )

    def test_fresh_process_no_advisory(self):
        # Artifact mtime (1970) older than the 2012 process start.
        manifest = {"claude:/home/me/claude": 0.0}
        runner = self._runner(5353, "Mon Jan 02 00:00:00 2012",
                              "/home/me/claude --resume def")
        procs, _ = doctor.probe_processes(
            "/home/me/claude", manifest, 5, ps_runner=runner)
        self.assertEqual(len(procs), 1)
        self.assertFalse(procs[0]["restart_required"])

    def test_non_claude_process_ignored(self):
        manifest = {"claude:/home/me/claude": 1900000000.0}
        runner = self._runner(1, "Mon Jan 02 00:00:00 2012",
                              "/usr/bin/curl https://example.invalid")
        procs, _ = doctor.probe_processes(
            "/home/me/claude", manifest, 5, ps_runner=runner)
        self.assertEqual(procs, [])

    def test_doctor_process_name_is_not_claude_process(self):
        manifest = {"claude:/home/me/claude": 1900000000.0}
        runner = self._runner(
            2,
            "Mon Jan 02 00:00:00 2012",
            "python3 /tmp/claude-session-hook-doctor.py",
        )
        procs, _ = doctor.probe_processes(
            "/home/me/claude", manifest, 5, ps_runner=runner
        )
        self.assertEqual(procs, [])

    def test_ps_unavailable_is_warning(self):
        def _r(_t):
            return 1, "", "no ps"
        procs, warns = doctor.probe_processes(
            None, {}, 5, ps_runner=_r)
        self.assertEqual(procs, [])
        self.assertTrue(any(w["code"] == "ps-unavailable" for w in warns))


class EndToEndAndParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doctor-e2e-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_report_never_serializes_env_values(self):
        rep = doctor.build_report(None, None, "unknown", [], [], [], [])
        self.assertFalse(rep["environment"]["env_values_serialized"])
        self.assertIn("CMUX_", rep["environment"]["denied_prefixes"])
        self.assertEqual(rep["summary"]["overall"], "healthy")

    def test_child_environment_drops_cmux_and_secret_values(self):
        old_cmux = os.environ.get("CMUX_SOCKET_CAPABILITY")
        old_secret = os.environ.get("DOCTOR_TEST_SECRET")
        os.environ["CMUX_SOCKET_CAPABILITY"] = "never-forward-me"
        os.environ["DOCTOR_TEST_SECRET"] = "never-forward-me-either"
        try:
            child = doctor._child_env()
        finally:
            if old_cmux is None:
                os.environ.pop("CMUX_SOCKET_CAPABILITY", None)
            else:
                os.environ["CMUX_SOCKET_CAPABILITY"] = old_cmux
            if old_secret is None:
                os.environ.pop("DOCTOR_TEST_SECRET", None)
            else:
                os.environ["DOCTOR_TEST_SECRET"] = old_secret
        self.assertNotIn("CMUX_SOCKET_CAPABILITY", child)
        self.assertNotIn("DOCTOR_TEST_SECRET", child)

    def test_stale_claude_version_is_error(self):
        issue = doctor.version_issue("2.1.210")
        self.assertIsNotNone(issue)
        self.assertEqual(issue["code"], "claude-version-stale")
        self.assertIsNone(doctor.version_issue("2.1.218"))

    def test_subprocess_capture_is_bounded(self):
        rc, out, err = doctor._run_argv(
            [
                sys.executable,
                "-c",
                f"import sys;sys.stdout.write('x'*{doctor.MAX_CAPTURE_BYTES + 1})",
            ],
            5,
        )
        self.assertEqual(rc, 125)
        self.assertEqual(out, "")
        self.assertIn("output exceeds", err)

    def test_strict_exit_on_restart_only(self):
        # Restart advisory present, no errors -> exit 0 normally, 1 with strict.
        manifest = {"claude:/x/claude": 1900000000.0}
        runner = self._runner(99, "Mon Jan 02 00:00:00 2012",
                              "/x/claude --resume")
        rep = doctor.build_report(None, None, "unknown", [], [],
                                  *doctor.probe_processes("/x/claude", manifest,
                                                          5, ps_runner=runner))
        self.assertTrue(rep["summary"]["restart_required"])
        self.assertEqual(rep["summary"]["errors"], 0)
        # Exercise the documented exit rule directly.
        self.assertEqual(_exit_code(rep, strict=False), 0)
        self.assertEqual(_exit_code(rep, strict=True), 1)

    def test_selftest_passes(self):
        self.assertEqual(doctor.selftest(), 0)

    def test_manifest_and_receipt_parity(self):
        manifest = install.load_manifest(SOURCE_ROOT)
        # The doctor is an executable in the bundle manifest.
        self.assertIn("scripts/claude-session-hook-doctor.py",
                      manifest.get("executable", []))
        # Knowledge payload maps it into the canonical (model-neutral) bundle.
        targets = {e["target"] for e in manifest["knowledge_payload"]}
        self.assertIn("scripts/claude-session-hook-doctor.py", targets)
        self.assertIn("references/SESSION_START_HEALTH.md", targets)
        # The Codex adapter payload lists both artifacts too.
        codex_payload = manifest["adapters"]["codex"]["payload"]
        self.assertIn("scripts/claude-session-hook-doctor.py", codex_payload)
        self.assertIn("references/SESSION_START_HEALTH.md", codex_payload)
        # Every source actually exists (installer would copy them).
        for rel, src in install.collect_knowledge_payload(SOURCE_ROOT, manifest):
            self.assertTrue(src.is_file(), f"missing payload source {src}")
        for rel, src in install.collect_codex_payload(SOURCE_ROOT, manifest):
            self.assertTrue(src.is_file(), f"missing adapter source {src}")

        # The Codex package-manifest lists both (required) and the doctor
        # (executable); otherwise validate-codex-skills.cjs would reject them.
        pkg = json.loads(
            (SKILL_DIR / "package-manifest.json").read_text(encoding="utf-8"))
        self.assertIn("scripts/claude-session-hook-doctor.py", pkg["required"])
        self.assertIn("scripts/claude-session-hook-doctor.py", pkg["executable"])
        self.assertIn("references/SESSION_START_HEALTH.md", pkg["required"])

    def test_plugins_json_override_path(self):
        good = self.tmp / "good"
        (good / "scripts").mkdir(parents=True)
        target = good / "scripts" / "r.sh"
        target.write_text("#!/bin/sh\n")
        _write_hooks(good, {"hooks": {doctor.SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command", "command": f"{self.sh} {target}"}]}]}})
        plist = self.tmp / "plugins.json"
        plist.write_text(json.dumps([
            {"id": "good", "enabled": True, "installPath": str(good)},
            {"id": "off", "enabled": False, "installPath": "/no/such"}]))
        plugins, warns = doctor.query_plugins(None, 5, str(plist))
        self.assertEqual(len(plugins), 2)
        self.assertEqual(warns, [])
        rep = doctor.validate_plugin(plugins[0])
        self.assertEqual(rep["status"], "healthy")

    @property
    def sh(self):
        return os.environ.get("SH") or __import__("shutil").which("sh") or "/bin/sh"

    def _runner(self, pid, lstart, command):
        text = f"{pid} {lstart} {command}\n"

        def _r(_t):
            return 0, text, ""
        return _r


def _exit_code(report: dict, strict: bool) -> int:
    summ = report["summary"]
    if summ["errors"]:
        return 1
    if strict and summ["restart_required"]:
        return 1
    return 0


if __name__ == "__main__":
    unittest.main(verbosity=2)

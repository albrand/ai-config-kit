from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/realdata-replay-gate.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, text=True,
                          capture_output=True).stdout.strip()


def replay_report() -> str:
    body = """# REALDATA-REPLAY

- Copy time (UTC): 2026-10-06T23:00:00Z
- Control SHA: 0123456789abcdef0123456789abcdef01234567
- Candidate SHA: 89abcdef0123456789abcdef0123456789abcdef
- Local copy: Mac-local database bound to loopback only; production data never leaves the Mac.
- Production source: read-only; no production writes were performed.
- Privacy: counts only; no row IDs or PII are included.
- Blocked rows: 0; external provider boundary was not needed for this replay.

| Goal | Target rows | Control count | Candidate count | Reason | Error class |
|---|---:|---:|---:|---|---|
| repair ingestion projection | 3 | 0 | 3 | records now project | none |
"""
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return body + f"- Artifact SHA-256 (excluding this line): {digest}\n"


class RealdataReplayGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "pallium-app"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "develop")
        git(self.repo, "config", "user.email", "gate@example.invalid")
        git(self.repo, "config", "user.name", "Gate fixture")
        git(self.repo, "remote", "add", "origin", "https://github.com/palliumai-com/pallium-app.git")
        (self.repo / "README.md").write_text("baseline\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "branch", "origin/develop", self.base)
        (self.repo / "src/server/ingestion").mkdir(parents=True)
        (self.repo / "src/server/ingestion/worker.ts").write_text("candidate\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "data fix")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def check(self, action: str = "review", command: str = "pre-review.py",
              env: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        result = subprocess.run([sys.executable, str(GATE), "check", "--repo", str(self.repo),
                                 "--base", self.base, "--action", action, "--command", command, "--json"],
                                text=True, capture_output=True, env=env)
        return result, json.loads(result.stdout)

    def test_missing_artifact_fails_then_valid_artifact_passes(self) -> None:
        missing, missing_json = self.check()
        self.assertEqual(missing.returncode, 2)
        self.assertFalse(missing_json["allowed"])
        self.assertIn("missing REALDATA-REPLAY.md", missing_json["reason"])

        (self.repo / "REALDATA-REPLAY.md").write_text(replay_report(), encoding="utf-8")
        passed, passed_json = self.check()
        self.assertEqual(passed.returncode, 0)
        self.assertTrue(passed_json["allowed"])
        self.assertEqual(passed_json["artifact"], "REALDATA-REPLAY.md")
        self.assertRegex(str(passed_json["sha256"]), r"^[0-9a-f]{64}$")

    def test_hermes_must_attach_report_or_a_packet_that_cites_it(self) -> None:
        report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        missing_citation, _ = self.check("review", "bb fleet validate 'review data fix'")
        self.assertEqual(missing_citation.returncode, 2)
        command_only_citation, _ = self.check("review", f"bb fleet validate 'REALDATA-REPLAY.md {digest}'")
        self.assertEqual(command_only_citation.returncode, 2)
        packet_only, _ = self.check("review", f"bb fleet validate --evidence packet.md")
        self.assertEqual(packet_only.returncode, 2)
        with_citation, _ = self.check("review", "bb fleet validate --evidence REALDATA-REPLAY.md")
        self.assertEqual(with_citation.returncode, 0)

    def test_digest_tampering_fails(self) -> None:
        report = replay_report().replace("| 3 | 0 | 3 |", "| 3 | 0 | 4 |")
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        result, payload = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertIn("SHA-256 does not match", payload["reason"])

    def test_release_requires_committed_report_and_citation(self) -> None:
        report = replay_report()
        (self.repo / "REALDATA-REPLAY.md").write_text(report, encoding="utf-8")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        missing_commit, _ = self.check("release", "release-request --evidence REALDATA-REPLAY.md")
        self.assertEqual(missing_commit.returncode, 2)
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "attach replay")
        request = self.repo / "release-request.md"
        request.write_text(f"Evidence: {request.parent / 'REALDATA-REPLAY.md'} SHA-256 {digest}\n", encoding="utf-8")
        allowed, _ = self.check("release", "release-request --evidence release-request.md")
        self.assertEqual(allowed.returncode, 0)

    def test_pr_ready_requires_report_digest_in_live_pr_body(self) -> None:
        report = replay_report()
        report_path = self.repo / "REALDATA-REPLAY.md"
        report_path.write_text(report, encoding="utf-8")
        git(self.repo, "add", "REALDATA-REPLAY.md")
        git(self.repo, "commit", "-m", "attach replay")
        digest = report.split("Artifact SHA-256 (excluding this line): ", 1)[1].strip()
        fake_bin = self.repo / "fake-bin"
        fake_bin.mkdir()
        gh = fake_bin / "gh"
        head = git(self.repo, "rev-parse", "HEAD")
        response = json.dumps({"body": f"{report_path.name} {digest}", "headRefOid": head,
                               "files": [{"path": "src/server/ingestion/worker.ts"},
                                         {"path": "REALDATA-REPLAY.md"}]})
        gh.write_text(f"#!/bin/sh\nprintf '%s\\n' '{response}'\n", encoding="utf-8")
        gh.chmod(0o755)
        import os
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        allowed, _ = self.check("pr", "gh pr ready", env)
        self.assertEqual(allowed.returncode, 0)

    def test_editable_path_inventory_matches_data_surfaces(self) -> None:
        from importlib.util import module_from_spec, spec_from_file_location
        spec = spec_from_file_location("realdata_gate", GATE)
        assert spec and spec.loader
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        expected = {
            "src/server/ingestion/job.ts", "src/server/services/integrations/client.ts",
            "src/server/intelligence/scoring.ts", "src/server/projections/account.ts",
            "src/server/readers/summary.ts", "src/server/repositories/account.ts",
            "prisma/migrations/20261001/migration.sql", "scripts/backfill.ts",
        }
        self.assertEqual(module.production_paths(expected), expected)


if __name__ == "__main__":
    unittest.main()

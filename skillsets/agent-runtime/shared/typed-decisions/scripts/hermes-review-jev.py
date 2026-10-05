#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


MAX_FINDINGS = 40
MAX_TEXT = 220
MAX_PACKET_BYTES = 30000
FIELDS = {"id", "kind", "path", "severity", "cause", "relation", "prior_id", "prior_summary", "changed_path", "summary"}
POINTS = {
    "j1": ("hermes-finding-kind", "named-defect|evidence-method|unclear"),
    "j2_duplicate": ("hermes-finding-dedupe", "new|duplicate|not-applicable|unclear"),
    "j2_cause": ("hermes-finding-cause", "delta|pre-existing|unclear"),
    "j3_path": ("hermes-finding-path", "changed|unchanged|unclear"),
    "j3_severity": ("hermes-finding-severity", "critical|high|medium|low|info|unclear"),
}
TEXT_REJECT = re.compile(
    r"(?:[\r\n`'\"{};]|\b(?:patient|cpf|ssn|date of birth|email address|phone number|home address)\b|"
    r"\b\d{3}[-.]?\d{3}[-.]?\d{3}[-/]?\d{2}\b|\b\d{2}/\d{2}/\d{4}\b|"
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b)",
    re.IGNORECASE,
)
CODE_REJECT = re.compile(r"(?:\b(?:function|const|let|var|return|import|export|SELECT|INSERT INTO)\b|=>|===|\+\+|--|@@|(?:^|\s)[+-](?:\s|[A-Za-z]))")
LABEL_RE = re.compile(r"^[A-Za-z0-9_./-]{1,120}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


def safe_summary(value):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise ValueError("finding summary is empty or over the limit")
    value = " ".join(value.split())
    if TEXT_REJECT.search(value) or CODE_REJECT.search(value):
        raise ValueError("finding summary contains code, personal data, or a secret-like value")
    if len(value.split()) > 32:
        raise ValueError("finding summary is too long")
    return value


def validate_packet(packet):
    if not isinstance(packet, dict) or set(packet) != {"review_ref", "hermes_verdict", "sensitive_context", "changed_paths", "findings"}:
        raise ValueError("review packet has unexpected fields")
    review_ref = packet["review_ref"]
    if not isinstance(review_ref, str) or not re.fullmatch(r"[A-Za-z0-9._:@#/-]{1,120}", review_ref):
        raise ValueError("review ref has an invalid shape")
    if packet["hermes_verdict"] not in {"accept", "revise", "reject"}:
        raise ValueError("Hermes verdict must be accept, revise, or reject")
    if not isinstance(packet["sensitive_context"], bool):
        raise ValueError("sensitive_context must be a boolean")
    changed_paths = packet["changed_paths"]
    if not isinstance(changed_paths, list) or len(changed_paths) > 100:
        raise ValueError("changed_paths must be a bounded label list")
    clean_paths = []
    for path in changed_paths:
        if not isinstance(path, str) or not LABEL_RE.fullmatch(path) or ".." in path:
            raise ValueError("changed path label has an invalid shape")
        clean_paths.append(path)
    findings = packet["findings"]
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        raise ValueError("review has an invalid number of findings")
    clean = []
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != FIELDS:
            raise ValueError("finding has unexpected fields")
        if not isinstance(finding["id"], str) or not ID_RE.fullmatch(finding["id"]):
            raise ValueError("finding id has an invalid shape")
        if finding["kind"] not in {"named-defect", "evidence-method", "unclear"}:
            raise ValueError("finding kind is outside its declared labels")
        if finding["severity"] not in {"critical", "high", "medium", "low", "info", "unclear"}:
            raise ValueError("finding severity is outside its declared labels")
        if finding["cause"] not in {"delta", "pre-existing", "unclear"}:
            raise ValueError("finding cause is outside its declared labels")
        if finding["relation"] not in {"new", "duplicate", "not-applicable", "unclear"}:
            raise ValueError("finding relation is outside its declared labels")
        if finding["changed_path"] not in {"changed", "unchanged", "unclear"}:
            raise ValueError("changed_path is outside its declared labels")
        path = finding["path"]
        if not isinstance(path, str) or not LABEL_RE.fullmatch(path) or ".." in path:
            raise ValueError("path label has an invalid shape")
        prior_id = finding["prior_id"]
        prior_summary = finding["prior_summary"]
        if prior_id not in ("", None):
            if not isinstance(prior_id, str) or not ID_RE.fullmatch(prior_id):
                raise ValueError("prior finding id has an invalid shape")
            prior_summary = safe_summary(prior_summary)
        elif prior_summary not in ("", None):
            raise ValueError("prior finding summary needs a prior id")
        clean.append({
            "id": finding["id"],
            "kind": finding["kind"],
            "path": path,
            "severity": finding["severity"],
            "cause": finding["cause"],
            "relation": finding["relation"],
            "prior_id": prior_id or "",
            "prior_summary": prior_summary or "",
            "changed_path": finding["changed_path"],
            "summary": safe_summary(finding["summary"]),
        })
    independent_items = [{"id": item["id"], "path": item["path"],
                          "prior_summary": item["prior_summary"], "summary": item["summary"]}
                         for item in clean]
    state = {
        "rules": {
            "j1": "Classify the bounded finding summary as a named defect, an evidence or method objection, or unclear. Do not infer a prior reviewer label.",
            "j2_duplicate": "Compare only the current and prior bounded finding summaries; decide new, duplicate, not-applicable when prior_summary is empty, or unclear.",
            "j2_cause": "Classify whether the described finding is caused by this delta, pre-existing, or unclear using only the supplied summaries.",
            "j3_path": "Classify whether the finding path appears in changed_paths, or unclear.",
            "j3_severity": "critical=data loss/auth bypass; high=major security/data/workflow impact; medium=material broken behavior with workaround; low=limited impact; info=non-defect observation; unclear=insufficient facts.",
        },
        "changed_paths": clean_paths,
        "items": independent_items,
    }
    if len(json.dumps(state, separators=(",", ":")).encode()) > MAX_PACKET_BYTES:
        raise ValueError("bounded review packet exceeds the size limit")
    return {"review_ref": review_ref, "hermes_verdict": packet["hermes_verdict"],
            "sensitive_context": packet["sensitive_context"], "changed_paths": clean_paths,
            "state": state, "findings": clean}


def build_questions(findings):
    questions = []
    points = []
    peers = []
    for finding in findings:
        for key, (point, options) in POINTS.items():
            qid = f"f{finding['id']}_{key}"
            question = f"For finding {finding['id']}, answer the {key} rule from the declared state. Do not rely on another reviewer's classification."
            questions.extend(("--pick", qid, question, options))
            points.append(f"{qid}={point}")
            peer_key = {"j1": "kind", "j2_duplicate": "relation", "j2_cause": "cause",
                        "j3_path": "changed_path", "j3_severity": "severity"}[key]
            peers.extend(("--peer-answer", qid, finding[peer_key]))
    return questions, ",".join(points), peers


def compose_result(findings, answers, base_ref):
    comparisons = []
    missing = []
    items = []
    for finding in findings:
        item = {"id": finding["id"], "answers": {}}
        comparisons_for_item = []
        recorded = []
        for key, (point, options) in POINTS.items():
            qid = f"f{finding['id']}_{key}"
            answer = answers.get(qid)
            if not isinstance(answer, dict) or answer.get("answer") not in options.split("|"):
                missing.append(qid)
                continue
            item["answers"][key] = answer["answer"]
            expected = {"j1": finding["kind"], "j2_duplicate": finding["relation"],
                        "j2_cause": finding["cause"], "j3_path": finding["changed_path"],
                        "j3_severity": finding["severity"]}[key]
            comparisons.append(answer["answer"] == expected)
            comparisons_for_item.append(answer["answer"] == expected)
            recorded.append(bool(answer.get("ledger")) and not answer["ledger"].startswith("refused:"))
        item["refs"] = [f"{base_ref} #f{finding['id']}_{key}" for key in POINTS]
        item["recorded"] = len(recorded) == len(POINTS) and all(recorded)
        item["status"] = "AGREEMENT" if comparisons_for_item and all(comparisons_for_item) and item["recorded"] else "ESCALATED"
        items.append(item)
    status = "AGREEMENT" if items and not missing and comparisons and all(comparisons) and all(item["recorded"] for item in items) else "ESCALATED"
    return status, items


def client_path():
    local = Path(__file__).with_name("jev.py")
    if local.is_file():
        return local
    for home in (Path.home() / ".agents", Path.home() / ".claude"):
        candidate = home / "skills/typed-decisions/scripts/jev.py"
        if candidate.is_file():
            return candidate
    return None


def run_judge(packet, script=None):
    if packet["sensitive_context"]:
        return {"status": "NOT RUN", "reason": "sensitive review context", "hermes_verdict": packet["hermes_verdict"]}
    if not packet["findings"]:
        return {"status": "NOT RUN", "reason": "no structured findings", "hermes_verdict": packet["hermes_verdict"]}
    script = script or client_path()
    if not script:
        return {"status": "NOT RUN", "reason": "installed Jev client not found", "hermes_verdict": packet["hermes_verdict"]}
    question_args, point_map, peers = build_questions(packet["findings"])
    command = [sys.executable, str(script), "--state-file", "-", *question_args,
               "--record", "--point", point_map, "--ref", f"jev-hermes:{packet['review_ref']}:c01", *peers]
    try:
        result = subprocess.run(command, input=json.dumps(packet["state"]), capture_output=True,
                                text=True, timeout=45, check=False)
        if result.returncode != 0:
            return {"status": "NOT RUN", "reason": "Jev client unavailable or refused the bounded packet",
                    "hermes_verdict": packet["hermes_verdict"]}
        response = json.loads(result.stdout)
        answers = response.get("answers")
        if not isinstance(answers, dict):
            raise ValueError("missing answers")
        base_ref = f"jev-hermes:{packet['review_ref']}:c01"
        status, items = compose_result(packet["findings"], answers, base_ref)
        return {"status": status, "hermes_verdict": packet["hermes_verdict"],
                "model": response.get("model", "Jev"), "usage": response.get("usage"),
                "latency_ms": response.get("latency_ms"), "items": items}
    except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
        return {"status": "NOT RUN", "reason": "Jev client failed; Hermes verdict remains unchanged",
                "hermes_verdict": packet["hermes_verdict"]}


def resolve_review(a):
    ledger = Path(__file__).with_name("decision-ledger.py")
    command = [sys.executable, str(ledger), "resolve-review", "--ref", a.ref,
               "--outcome", a.outcome, "--evidence", a.evidence]
    if a.finding:
        command.extend(("--finding", a.finding))
    result = subprocess.run(command,
                            capture_output=True, text=True, check=False)
    sys.stdout.write(result.stdout)
    if result.returncode:
        sys.stderr.write("decision ledger could not resolve the review\n")
    return result.returncode


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    judge = sub.add_parser("judge")
    judge.add_argument("packet")
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--ref", required=True)
    resolve.add_argument("--outcome", choices=("held", "overturned"), required=True)
    resolve.add_argument("--evidence", required=True)
    resolve.add_argument("--finding")
    args = parser.parse_args()
    if args.command == "resolve":
        return resolve_review(args)
    try:
        packet = validate_packet(json.loads(Path(args.packet).read_text(encoding="utf-8")))
        result = run_judge(packet)
    except (OSError, ValueError, json.JSONDecodeError):
        result = {"status": "NOT RUN", "reason": "review packet rejected; Hermes verdict remains unchanged"}
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

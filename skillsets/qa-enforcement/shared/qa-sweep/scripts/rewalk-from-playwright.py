#!/usr/bin/env python3
"""Build a QA rewalk.json from a Playwright JSON reporter artifact."""
import argparse
import json
import os
import sys


def fail(message):
    raise ValueError(message)


def read_json(path, label):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{label} could not be read as JSON: {exc}")


def walk_suites(suites):
    for suite in suites if isinstance(suites, list) else []:
        if not isinstance(suite, dict):
            continue
        for spec in suite.get("specs", []) if isinstance(suite.get("specs"), list) else []:
            if not isinstance(spec, dict):
                continue
            tests = spec.get("tests", [])
            for test in tests if isinstance(tests, list) else []:
                if isinstance(test, dict):
                    yield test
        yield from walk_suites(suite.get("suites", []))


def annotation_texts(test):
    annotations = test.get("annotations", [])
    if not isinstance(annotations, list):
        return set()
    return {a.get("description") for a in annotations
            if isinstance(a, dict) and a.get("type") == "qa-step"
            and isinstance(a.get("description"), str)}


def attempt_results(test):
    results = test.get("results", [])
    if not isinstance(results, list) or not results:
        return []
    return sorted(results, key=lambda result: result.get("retry", 0)
                  if isinstance(result, dict) and isinstance(result.get("retry", 0), int) else 0)


def test_outcome(test):
    """Return (passed_first_try, note) using Playwright's first result only."""
    results = attempt_results(test)
    status = str(test.get("status") or "")
    expected = str(test.get("expectedStatus") or "")
    if expected == "skipped" or status == "skipped":
        return False, "skipped test is a failure for re-walk coverage"
    if status not in ("expected", "passed", "flaky"):
        return False, f"Playwright test status was {status!r}, not a passing status"
    if not results:
        return False, "test has no result attempt"
    first_attempts = [r for r in results if isinstance(r, dict) and r.get("retry") == 0]
    if len(first_attempts) != 1:
        return False, "test does not have exactly one retry=0 first attempt"
    first = first_attempts[0]
    first_status = first.get("status") if isinstance(first, dict) else None
    later_passed = any(isinstance(r, dict) and r.get("status") == "passed" for r in results[1:])
    if first_status != "passed":
        if later_passed or status == "flaky":
            return False, "flaky: first attempt did not pass (later retry passed)"
        return False, f"first attempt status was {first_status!r}"
    if status == "flaky":
        return False, "flaky test is a failure for re-walk coverage"
    if expected and expected != "passed":
        return False, f"expected status was {expected!r}, not 'passed'"
    return True, "passed on first attempt"


def attachment_paths(test):
    paths = []
    for result in attempt_results(test):
        attachments = result.get("attachments", []) if isinstance(result, dict) else []
        for attachment in attachments if isinstance(attachments, list) else []:
            if not isinstance(attachment, dict):
                continue
            name = str(attachment.get("name") or "").lower()
            content_type = str(attachment.get("contentType") or "").lower()
            path = attachment.get("path")
            is_trace_or_screenshot = ("trace" in name or "screenshot" in name
                                      or content_type.startswith("image/"))
            if is_trace_or_screenshot and isinstance(path, str) and path.strip() and path not in paths:
                paths.append(path)
    return paths


def build_rewalk(report, workflow, sha, target, deployment_id, report_path):
    if not isinstance(report, dict):
        fail("Playwright JSON report must be an object")
    if not isinstance(workflow, dict):
        fail("workflow.json must be an object")
    workflow_name = workflow.get("workflow")
    if not isinstance(workflow_name, str) or not workflow_name.strip():
        fail("workflow.json needs a non-empty 'workflow' name matching .qa/config.json")
    steps = workflow.get("steps")
    if not isinstance(steps, list) or not steps or any(not isinstance(step, str) or not step.strip() for step in steps):
        fail("workflow.json steps must be a non-empty list of names")
    if len(set(steps)) != len(steps):
        fail("workflow.json steps must have unique names")

    tests_by_step = {step: [] for step in steps}
    for test in walk_suites(report.get("suites", [])):
        for annotation in annotation_texts(test):
            prefix = workflow_name + "::"
            if annotation.startswith(prefix):
                step = annotation[len(prefix):]
                if step in tests_by_step:
                    tests_by_step[step].append(test)

    output_steps = []
    for step in steps:
        tests = tests_by_step[step]
        evidence = [report_path]
        notes = []
        for test in tests:
            passed, note = test_outcome(test)
            if not passed:
                title = str(test.get("title") or test.get("projectName") or "annotated Playwright test")
                notes.append(f"{title}: {note}")
            evidence.extend(path for path in attachment_paths(test) if path not in evidence)
        if not tests:
            verdict = "NOT_AUTOMATED"
            note = "No Playwright test is annotated for this workflow step; manual walk evidence is required."
        else:
            verdict = "PASS" if not notes else "FAIL"
            note = "; ".join(notes) if notes else "All annotated tests passed on their first attempt."
        output_steps.append({"step": step, "verdict": verdict, "evidence": evidence, "note": note})

    return {
        "sha": sha,
        "target": target,
        "deployment_id": deployment_id,
        "workflow": workflow_name,
        "report": report_path,
        "steps": output_steps,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="Playwright JSON reporter file")
    parser.add_argument("workflow", help="the run's workflow.json")
    parser.add_argument("--sha", required=True, help="full commit SHA covered by the run")
    parser.add_argument("--target", required=True, help="preview URL used for the run")
    parser.add_argument("--deployment-id", required=True, help="deployment identifier for the preview")
    parser.add_argument("--output", default="rewalk.json", help="output path (default: ./rewalk.json)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not args.sha.strip() or not args.target.strip() or not args.deployment_id.strip():
        print("sha, target, and deployment-id must be non-empty", file=sys.stderr)
        return 2
    try:
        report = read_json(args.report, "Playwright report")
        workflow = read_json(args.workflow, "workflow.json")
        result = build_rewalk(report, workflow, args.sha, args.target, args.deployment_id, args.report)
        parent = os.path.dirname(os.path.abspath(args.output))
        os.makedirs(parent, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"wrote {args.output}: {len(result['steps'])} workflow step(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

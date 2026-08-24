#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { evaluateEvidence } from "../scripts/qa-e2e-gate.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(fs.readFileSync(path.join(here, "fixtures.json"), "utf8"));
const efforts = ["low", "medium", "high", "xhigh", "max"];

for (const fixture of fixtures) {
  let baselineCodes = null;
  for (const effort of efforts) {
    const packet = structuredClone(fixture.packet);
    packet.reasoning_effort = effort;
    const result = evaluateEvidence(packet);
    assert.equal(result.ok, fixture.expected, `${fixture.id} at ${effort}`);
    assert.equal(result.reasoning_invariant, true, `${fixture.id} reasoning invariant marker`);
    const codes = result.failures.map((item) => item.code).sort();
    if (baselineCodes === null) baselineCodes = codes;
    else assert.deepEqual(codes, baselineCodes, `${fixture.id} changed outcome at ${effort}`);
    for (const code of fixture.required_codes ?? []) {
      assert.ok(codes.includes(code), `${fixture.id} missing ${code} at ${effort}`);
    }
  }
}

process.stdout.write(
  JSON.stringify({ ok: true, fixtures: fixtures.length, efforts, evaluations: fixtures.length * efforts.length }) + "\n",
);

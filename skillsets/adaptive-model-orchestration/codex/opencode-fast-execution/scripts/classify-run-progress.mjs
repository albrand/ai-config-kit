#!/usr/bin/env node

import fs from 'node:fs';

const input = process.argv[2]
  ? fs.readFileSync(process.argv[2], 'utf8')
  : fs.readFileSync(0, 'utf8');
const evidence = JSON.parse(input);
const processState = evidence.process_state ?? 'unknown';
const terminalStates = ['completed', 'exited', 'failed', 'stopped'];
const repairAttempts = Number(evidence.repair_attempts ?? 0);
const telemetry = {
  elapsed_ms: evidence.elapsed_ms ?? null,
  outer_silence_ms: evidence.outer_silence_ms ?? null,
  pre_edit_tools: evidence.pre_edit_tools ?? null,
  tool_calls: evidence.tool_calls ?? null,
  validation_calls: evidence.validation_calls ?? null,
};
const verifiedViolations = [
  ['scope', evidence.verified_scope_violation === true],
  ['security', evidence.verified_security_violation === true],
  ['destructive_action', evidence.verified_destructive_violation === true],
].filter(([, present]) => present);
let decision = 'continue';
const reasons = [];

if (verifiedViolations.length > 0) {
  decision = 'stop';
  reasons.push(`verified violation: ${verifiedViolations.map(([name]) => name).join(', ')}`);
} else if (evidence.provider_error || evidence.fatal_protocol_error) {
  decision = 'stop';
  reasons.push(evidence.provider_error ? 'provider error' : 'fatal protocol error');
} else if (evidence.caller_signal) {
  decision = 'stop';
  reasons.push(`caller cancellation: ${evidence.caller_signal}`);
} else if (evidence.explicit_deadline_expired === true) {
  decision = 'stop';
  reasons.push('predeclared wall deadline expired');
} else if (['running', 'starting'].includes(processState)) {
  decision = 'continue';
  reasons.push('owned process is still live without a hard-stop condition');
} else if (!terminalStates.includes(processState)) {
  decision = 'continue';
  reasons.push('terminal process state is not confirmed; repair is not authorized');
} else if (evidence.process_quiescent !== true) {
  decision = 'continue';
  reasons.push('process-tree quiescence is not confirmed; completion and repair are not authorized');
} else if (
  evidence.result_status === 'done' &&
  evidence.acceptance_criteria_met === true &&
  evidence.close_out_complete === true
) {
  decision = 'complete';
  reasons.push('completed result satisfies acceptance criteria and close-out contract');
} else if (repairAttempts < 1) {
  decision = 'repair';
  reasons.push('completed result is insufficient and one compact repair remains');
} else {
  decision = 'escalate';
  reasons.push('completed result is insufficient after the single repair allowance');
}

reasons.push('tool, validation, elapsed-time, and outer-silence counts are telemetry only');

process.stdout.write(`${JSON.stringify({ decision, reasons, telemetry }, null, 2)}\n`);

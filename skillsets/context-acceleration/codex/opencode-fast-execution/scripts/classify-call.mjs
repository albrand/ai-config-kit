#!/usr/bin/env node

import fs from 'node:fs';

const input = process.argv[2] ? fs.readFileSync(process.argv[2], 'utf8') : fs.readFileSync(0, 'utf8');
const packet = JSON.parse(input);
const required = ['objective', 'scope', 'inputs', 'output', 'escalation'];
const missing = required.filter((key) => !packet[key]);

let classification = 'execute';
const reasons = [];
if (packet.mode === 'advisor' || packet.marker === 'ADVISOR_PACKET_V1') {
  classification = 'advisor';
  reasons.push('explicit evidence-only advisor marker');
} else if (packet.previous_status || packet.failed_gate || packet.repair_reason) {
  classification = 'repair';
  reasons.push('prior run contains failure or repair evidence');
} else {
  reasons.push('complete implementation packet without prior failure');
}

if (missing.length > 0) {
  classification = 'blocked';
  reasons.push(`missing packet fields: ${missing.join(', ')}`);
}

process.stdout.write(`${JSON.stringify({ classification, reasons, required_fields: required }, null, 2)}\n`);

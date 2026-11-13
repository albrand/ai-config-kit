import { appendFileSync } from 'node:fs';

/** Fixture helper for the cleanup ledger: call once per record a test creates in a deployed environment. */
export function recordOwned(kind, id, file = process.env.QA_OWNS_FILE) {
  if (!file) return false;
  appendFileSync(file, `${JSON.stringify({ kind: String(kind), id: String(id) })}\n`);
  return true;
}

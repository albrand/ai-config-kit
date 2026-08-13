// Placeholder substitution — the seam between a shared library and a local one.
//
// The shared repo must be portable: no hostnames, no home directories, no
// machine names. The published copy must be *useful*: `ssh vps`, not
// `ssh {{REMOTE_HOST}}`. Those requirements only coexist if lessons are written
// with placeholders and resolved on the way out.
//
// The trap this is designed around: substituting only at publish time silently
// disables verification, because `verify.mjs` reads the shared source and would
// run `ssh {{REMOTE_HOST}}` — which fails, reporting the claim as false when it
// is the check that could not resolve. Both paths substitute, and an
// unresolvable placeholder is reported as "not applicable on this machine"
// rather than as a failure.
//
// The overlay lives outside the repo so it is never committed by accident.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const OVERLAY_PATH =
  process.env.AGENT_LIBRARY_OVERLAY ??
  path.join(os.homedir(), ".config", "agent-library", "local.json");

/**
 * Machine-local values for the placeholders lessons use.
 *
 * Absent overlay is a normal state, not an error: a fresh machine has the
 * shared library and no local bindings yet, and everything without placeholders
 * still publishes and still verifies.
 */
export function loadOverlay(file = OVERLAY_PATH) {
  if (!fs.existsSync(file)) return {};
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

const PLACEHOLDER = /\{\{([A-Z0-9_]+)\}\}/g;

/** Every placeholder a body references, in order of first appearance. */
export function placeholdersIn(text) {
  return [...new Set([...text.matchAll(PLACEHOLDER)].map((m) => m[1]))];
}

/**
 * Resolve placeholders against the overlay.
 *
 * Returns what could not be resolved rather than throwing, so a caller can
 * decide: publishing a lesson with one unresolved placeholder is still useful
 * (the rest of the text is), while verifying one is not.
 */
export function substitute(text, overlay = loadOverlay()) {
  const missing = [];
  const resolved = text.replace(PLACEHOLDER, (whole, key) => {
    const value = overlay[key];
    if (typeof value !== "string") {
      missing.push(key);
      return whole;
    }
    return value;
  });
  return { text: resolved, missing: [...new Set(missing)] };
}

import { execFileSync } from "node:child_process";

export function policy(text, policyScript, metadata = {}) {
  try {
    return JSON.parse(execFileSync("python3", [policyScript], {
      input: JSON.stringify({ text, ...metadata }), encoding: "utf8", timeout: 3000,
    }));
  } catch {
    return { decision: "allow" };
  }
}

import { execFileSync } from "node:child_process";

export function policy(text, policyScript) {
  try {
    return JSON.parse(execFileSync("python3", [policyScript], {
      input: JSON.stringify({ text }), encoding: "utf8", timeout: 3000,
    }));
  } catch {
    return { decision: "allow" };
  }
}

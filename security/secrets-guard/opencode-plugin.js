import { execFileSync } from "node:child_process";

const PYTHON = "/usr/bin/python3";
const GUARD = `${process.env.HOME}/.agent-hooks/secrets-guard.py`;
const SCRUBBER = `${process.env.HOME}/.agent-hooks/secrets-scrub-exec.py`;
const quote = (s) => `'${String(s).replace(/'/g, "'\\''")}'`;

export const server = async () => ({
  "tool.execute.before": async (input, output) => {
    const tool = String(input?.tool ?? "").toLowerCase();
    if (!/^(bash|shell|run_command|exec)$/.test(tool)) return;
    const command = output?.args?.command ?? output?.args?.cmd;
    if (typeof command !== "string") throw new Error("Secret guard failed closed; command not run.");
    let verdict;
    try {
      verdict = JSON.parse(execFileSync(PYTHON, [GUARD], {
        input: JSON.stringify({ tool_input: { command } }), encoding: "utf8", timeout: 5000,
      }));
    } catch {
      throw new Error("Secret guard failed closed; command not run.");
    }
    if (verdict?.block) throw new Error(String(verdict.reason || "Secret output blocked."));
    output.args.command = `${quote(PYTHON)} ${quote(SCRUBBER)} -- ${quote(command)}`;
  },
});

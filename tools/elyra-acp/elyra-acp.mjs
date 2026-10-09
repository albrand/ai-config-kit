#!/usr/bin/env node
// elyra-acp: an ACP agent that bb launches as a provider. Each bb thread's
// turns run in an Elyra terminal card under the native interactive `claude`
// CLI; the session transcript is tailed and streamed back to bb as ACP
// session/update notifications. bb stays the control plane, Elyra is the
// runtime. One Elyra card per Claude session; the card title is the stable
// address (handles die with an app restart).
import fs from "node:fs";
import os from "node:os";
import readline from "node:readline";
import childProcess from "node:child_process";
import crypto from "node:crypto";

const HOME = os.homedir();
const CONFIG_PATH = process.env.ELYRA_ACP_CONFIG || HOME + "/.config/elyra-acp/config.json";
const STATE_DIR = HOME + "/.local/state/elyra-acp";
const RUN_DIR = STATE_DIR + "/run";
const REGISTRY_PATH = STATE_DIR + "/sessions.json";
const LOG_PATH = STATE_DIR + "/bridge.log";
fs.mkdirSync(RUN_DIR, { recursive: true, mode: 0o700 });

const DEFAULTS = {
  elyraCli: "/Applications/Elyra ADE.app/Contents/Resources/bin/elyra",
  claudeBin: HOME + "/.local/bin/claude",
  poolEnvCommand: HOME + "/.local/bin/elyra-pool env",
  // Elyra workspace whose path is the longest prefix of the session cwd wins;
  // otherwise this one hosts the card.
  fallbackWorkspace: null,
  models: [
    { modelId: "claude-opus-5-5[1m]", name: "Opus 5.5 (1M)", effort: "high" },
    { modelId: "claude-sonnet-5-5", name: "Sonnet 5.5", effort: "low" },
    { modelId: "claude-haiku-5-5", name: "Haiku 5.5", effort: "low" },
  ],
  defaultModel: "claude-sonnet-5-5",
  // bbThreadId -> { resumeSessionId, approvedBy, approvedAt }. A user-approved
  // record; the bridge never infers a resume target from prompt text.
  imports: {},
  pollMs: 400,
  idleSettleMs: 1500,
  toolResultMaxChars: 4000,
  cancelGraceMs: 2500,
};

const loadConfig = () => {
  let user = {};
  try { user = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8")); } catch {}
  return { ...DEFAULTS, ...user };
};
const config = loadConfig();

const SECRETISH = /TOKEN|SECRET|KEY|PASSWORD|AUTH|COOKIE/i;
const log = (o) => {
  try { fs.appendFileSync(LOG_PATH, JSON.stringify({ t: new Date().toISOString(), pid: process.pid, thread: process.env.BB_THREAD_ID, ...o }) + "\n", { mode: 0o600 }); } catch {}
};

// ---------- registry (session -> card) ----------
const readRegistry = () => { try { return JSON.parse(fs.readFileSync(REGISTRY_PATH, "utf8")); } catch { return {}; } };
const writeRegistry = (reg) => {
  const tmp = REGISTRY_PATH + "." + process.pid;
  fs.writeFileSync(tmp, JSON.stringify(reg, null, 1), { mode: 0o600 });
  fs.renameSync(tmp, REGISTRY_PATH);
};
const updateRegistry = (sessionId, patch) => {
  const reg = readRegistry();
  reg[sessionId] = { ...(reg[sessionId] || {}), ...patch, updatedAt: new Date().toISOString() };
  writeRegistry(reg);
  return reg[sessionId];
};

// ---------- elyra CLI ----------
const elyra = (args, { input, timeoutMs = 60000 } = {}) => new Promise((resolve) => {
  const child = childProcess.execFile(config.elyraCli, [...args, "--json"], { timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024, env: { HOME, PATH: "/usr/bin:/bin:/usr/sbin:/sbin" } }, (err, stdout, stderr) => {
    let parsed = null;
    try { parsed = JSON.parse(stdout); } catch {}
    if (!parsed) parsed = { ok: false, error: { message: (stderr || stdout || String(err)).slice(0, 800) } };
    resolve(parsed);
  });
  if (input !== undefined) { child.stdin.end(input); }
});

const listWorkspaces = async () => {
  const r = await elyra(["workspace", "list"]);
  const items = r.result?.worktrees || [];
  return items.filter((w) => w && typeof w === "object" && !w.isArchived);
};

const pickWorkspace = async (cwd) => {
  const real = (p) => { try { return fs.realpathSync(p); } catch { return p; } };
  const target = real(cwd);
  let best = null;
  for (const w of await listWorkspaces()) {
    const p = w.path || w.worktreePath || w.rootPath;
    if (!p) continue;
    const rp = real(p);
    if ((target === rp || target.startsWith(rp + "/")) && (!best || rp.length > best.len)) best = { id: w.id, len: rp.length };
  }
  if (best) return "id:" + best.id;
  if (config.fallbackWorkspace) return config.fallbackWorkspace;
  throw new Error(`No Elyra workspace contains ${cwd}; set fallbackWorkspace in ${CONFIG_PATH}`);
};

const cardAlive = async (title) => {
  const r = await elyra(["terminal", "show", "--terminal", title]);
  const t = r.ok ? r.result?.terminal : null;
  return !!t && t.connected !== false && !/exited|stopped|closed/.test(String(t.status || ""));
};

// ---------- transcript ----------
const projectKey = (cwd) => cwd.replace(/[^A-Za-z0-9]/g, "-");
const findTranscript = (sessionId, cwd) => {
  const base = HOME + "/.claude/projects";
  const guesses = [cwd, (() => { try { return fs.realpathSync(cwd); } catch { return cwd; } })()].map((c) => `${base}/${projectKey(c)}/${sessionId}.jsonl`);
  for (const g of guesses) if (fs.existsSync(g)) return g;
  try {
    for (const d of fs.readdirSync(base)) {
      const p = `${base}/${d}/${sessionId}.jsonl`;
      if (fs.existsSync(p)) return p;
    }
  } catch {}
  return null;
};

class Tail {
  constructor(sessionId, cwd, offset) { this.sessionId = sessionId; this.cwd = cwd; this.path = null; this.offset = offset ?? null; this.partial = ""; }
  locate() {
    if (!this.path) this.path = findTranscript(this.sessionId, this.cwd);
    if (this.path && this.offset === null) this.offset = fs.statSync(this.path).size;
    return this.path;
  }
  read() {
    if (!this.locate()) return [];
    const size = fs.statSync(this.path).size;
    if (size <= this.offset) return [];
    const fd = fs.openSync(this.path, "r");
    const buf = Buffer.alloc(size - this.offset);
    fs.readSync(fd, buf, 0, buf.length, this.offset);
    fs.closeSync(fd);
    this.offset = size;
    const text = this.partial + buf.toString("utf8");
    const lines = text.split("\n");
    this.partial = lines.pop();
    const out = [];
    for (const l of lines) { if (!l.trim()) continue; try { out.push(JSON.parse(l)); } catch {} }
    return out;
  }
}

const toolKind = (name) => {
  if (/^(Read|Glob|Grep|LS|NotebookRead)$/.test(name)) return "read";
  if (/^(Edit|Write|MultiEdit|NotebookEdit)$/.test(name)) return "edit";
  if (/^(Bash|BashOutput|KillShell)$/.test(name)) return "execute";
  if (/^(WebFetch|WebSearch)$/.test(name)) return "fetch";
  if (/^(Task|Agent)$/.test(name)) return "think";
  return "other";
};
const toolTitle = (name, input) => {
  const i = input || {};
  const brief = i.description || i.command || i.file_path || i.pattern || i.url || i.query || i.prompt || "";
  return `${name}${brief ? ": " + String(brief).replace(/\s+/g, " ").slice(0, 160) : ""}`;
};
const resultText = (content) => {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map((c) => (c.type === "text" ? c.text : `[${c.type}]`)).join("\n");
  return JSON.stringify(content ?? "");
};

// Map one transcript entry to ACP updates. Returns { updates, userText, turnEnded }.
const mapEntry = (e) => {
  const updates = [];
  let userText = null;
  let turnEnded = false;
  const m = e.message || {};
  if (e.type === "assistant" && !e.isSidechain) {
    for (const c of Array.isArray(m.content) ? m.content : []) {
      if (c.type === "text" && c.text) updates.push({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: c.text } });
      else if (c.type === "thinking" && c.thinking) updates.push({ sessionUpdate: "agent_thought_chunk", content: { type: "text", text: c.thinking } });
      else if (c.type === "tool_use") updates.push({ sessionUpdate: "tool_call", toolCallId: c.id, title: toolTitle(c.name, c.input), kind: toolKind(c.name), status: "in_progress", rawInput: c.input });
    }
  } else if (e.type === "user" && !e.isSidechain && !e.isMeta) {
    if (typeof m.content === "string") userText = m.content;
    for (const c of Array.isArray(m.content) ? m.content : []) {
      if (c.type === "tool_result") {
        let text = resultText(c.content);
        if (text.length > config.toolResultMaxChars) text = text.slice(0, config.toolResultMaxChars) + `\n… (${text.length - config.toolResultMaxChars} more chars in the Elyra card)`;
        updates.push({ sessionUpdate: "tool_call_update", toolCallId: c.tool_use_id, status: c.is_error ? "failed" : "completed", content: [{ type: "content", content: { type: "text", text } }] });
      } else if (c.type === "text" && c.text) userText = (userText ? userText + "\n" : "") + c.text;
    }
  } else if (e.type === "system" && e.subtype === "stop_hook_summary") {
    turnEnded = true;
  }
  return { updates, userText, turnEnded };
};

// ---------- ACP transport ----------
const out = (msg) => process.stdout.write(JSON.stringify({ jsonrpc: "2.0", ...msg }) + "\n");
const notify = (sessionId, update) => out({ method: "session/update", params: { sessionId, update } });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- session ----------
// The user approved (2026-10-09) trusting only folders bb created for its own
// threads; any other folder still stops at Claude's trust prompt.
const AUTO_TRUST_PREFIXES = [HOME + "/.bb/plugins/environment-git-worktree/host-data/worktrees/", HOME + "/.bb/thread-storage/"];
const autoTrustable = (cwd) => {
  let real = cwd;
  try { real = fs.realpathSync(cwd); } catch {}
  return AUTO_TRUST_PREFIXES.some((p) => real.startsWith(p) && !real.slice(p.length).split("/").includes(".."));
};
const markTrusted = (cwd) => {
  const path = HOME + "/.claude.json";
  try {
    const data = JSON.parse(fs.readFileSync(path, "utf8"));
    data.projects = data.projects || {};
    const entry = data.projects[cwd] || {};
    if (entry.hasTrustDialogAccepted) return;
    data.projects[cwd] = { ...entry, hasTrustDialogAccepted: true };
    const tmp = `${path}.elyra-acp.${process.pid}`;
    fs.writeFileSync(tmp, JSON.stringify(data, null, 2), { mode: 0o600 });
    fs.renameSync(tmp, path);
    log({ event: "auto-trusted", cwd });
  } catch (e) { log({ event: "auto-trust-failed", cwd, error: String(e) }); }
};

const shq = (s) => "'" + String(s).replace(/'/g, "'\\''") + "'";
const LEAKED_ENV = ["CLAUDECODE", "CLAUDE_AGENT_SDK_VERSION", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_DISABLE_1M_CONTEXT", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_EFFORT", "CLAUDE_PID", "CODEX_CI", "CODEX_SESSION_ID", "CODEX_THREAD_ID", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL"];
const BB_IDENTITY = ["BB_CLI", "BB_SERVER_URL", "BB_HOST_DAEMON_PORT", "BB_PROJECT_ID", "BB_THREAD_STORAGE", "BB_THREAD_ID", "BB_ENVIRONMENT_ID"];

const mcpConfigFrom = (mcpServers) => {
  const servers = {};
  for (const s of mcpServers || []) {
    if (!s || !s.name) continue;
    if (s.command) {
      const env = {};
      for (const kv of s.env || []) env[kv.name] = kv.value;
      servers[s.name] = { type: "stdio", command: s.command, args: s.args || [], env };
    } else if (s.url) {
      const headers = {};
      for (const kv of s.headers || []) headers[kv.name] = kv.value;
      servers[s.name] = { type: s.type === "sse" ? "sse" : "http", url: s.url, headers };
    }
  }
  return { mcpServers: servers };
};

class Session {
  constructor({ sessionId, cwd, mcpServers, model, resume }) {
    this.sessionId = sessionId;
    this.cwd = cwd;
    this.mcpServers = mcpServers;
    this.model = model;
    this.resume = resume;
    this.cardTitle = null;
    this.tail = null;
    this.prompting = false;
    this.cancelled = false;
    this.idleBuffer = [];
    this.watcher = null;
  }

  effortFor(model) { return (config.models.find((m) => m.modelId === model) || {}).effort || "low"; }

  async titleForCard() {
    const tid = process.env.BB_THREAD_ID || "nothread";
    let title = "";
    try {
      const cli = process.env.BB_CLI;
      if (cli) {
        const r = childProcess.execFileSync(process.execPath, [cli, "thread", "show", tid, "--json"], { timeout: 15000, env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" } }).toString();
        title = (JSON.parse(r).thread?.title || "").slice(0, 48);
      }
    } catch {}
    return `bb ${tid}${title ? " · " + title : ""}`;
  }

  writeLaunchScript() {
    const id = this.sessionId;
    const mcpPath = `${RUN_DIR}/${id}.mcp.json`;
    fs.writeFileSync(mcpPath, JSON.stringify(mcpConfigFrom(this.mcpServers)), { mode: 0o600 });
    const lines = ["#!/bin/zsh", "set -e"];
    lines.push("unset " + LEAKED_ENV.join(" "));
    for (const k of BB_IDENTITY) if (process.env[k]) lines.push(`export ${k}=${shq(process.env[k])}`);
    lines.push(`export ELYRA_ACP_SESSION=${shq(id)}`);
    // Pool routing: bb's own pool bridge, which also keeps the 1M window.
    if (config.poolEnvCommand) lines.push(`eval "$(${config.poolEnvCommand})"`);
    lines.push(`cd ${shq(this.cwd)}`);
    const args = [config.claudeBin, this.resume ? "--resume" : "--session-id", id, "--model", this.model, "--effort", this.effortFor(this.model), "--dangerously-skip-permissions", "--mcp-config", mcpPath, "--disallowedTools", "AskUserQuestion"];
    // bb's harness instructions go in the system prompt once, not into every
    // typed turn (they are ~49K chars).
    if (this.systemText) {
      const sysPath = `${RUN_DIR}/${id}.system.md`;
      fs.writeFileSync(sysPath, this.systemText, { mode: 0o600 });
      args.push("--append-system-prompt-file", sysPath);
    }
    // Not exec: record how claude ended, then exit so the card never falls
    // back to a shell that would run typed turns as commands.
    lines.push("set +e", args.map(shq).join(" "), `echo "$(date -u +%FT%TZ) exit=$?" >> ${shq(`${RUN_DIR}/${id}.exit`)}`, "exit 0");
    const scriptPath = `${RUN_DIR}/${id}.sh`;
    fs.writeFileSync(scriptPath, lines.join("\n") + "\n", { mode: 0o700 });
    return scriptPath;
  }

  async ensureCard() {
    const reg = readRegistry()[this.sessionId];
    if (reg?.cardTitle && (await cardAlive(reg.cardTitle))) {
      this.cardTitle = reg.cardTitle;
      log({ event: "card-reused", sessionId: this.sessionId, card: this.cardTitle });
      return;
    }
    // Resume only when there is a conversation to resume; `--resume` on an
    // unknown id exits at once.
    this.resume = !!findTranscript(this.sessionId, this.cwd);
    const workspace = reg?.workspace || (await pickWorkspace(this.cwd));
    if (reg?.cardTitle) {
      // The card survives its process: reopen it as a shell and relaunch.
      this.cardTitle = reg.cardTitle;
      const shown = await elyra(["terminal", "show", "--terminal", this.cardTitle]);
      const reopened = await elyra(["terminal", "reopen", "--terminal", this.cardTitle, "--workspace", workspace]);
      log({ event: "card-reopen", card: this.cardTitle, status: shown.result?.terminal?.status, connected: shown.result?.terminal?.connected, ok: reopened.ok, error: reopened.error?.message });
      if (!reopened.ok) throw new Error(`Elyra card "${this.cardTitle}" exists but could not be reopened: ${reopened.error?.message || "unknown"}`);
    } else {
      this.cardTitle = await this.titleForCard();
      const created = await elyra(["canvas", "create", "terminal", "--workspace", workspace, "--cwd", this.cwd, "--title", this.cardTitle]);
      if (!created.ok) throw new Error("Elyra card creation failed: " + (created.error?.message || "unknown"));
    }
    if (autoTrustable(this.cwd)) markTrusted(this.cwd);
    const script = this.writeLaunchScript();
    await sleep(2500); // let the shell come up before typing
    const sent = await elyra(["terminal", "send", "--terminal", this.cardTitle, "--text", `exec ${shq(script)}`]);
    if (!sent.ok) throw new Error("Elyra launch send failed: " + (sent.error?.message || "unknown"));
    updateRegistry(this.sessionId, { cardTitle: this.cardTitle, cwd: this.cwd, workspace, bbThreadId: process.env.BB_THREAD_ID, model: this.model });
    log({ event: "card-created", sessionId: this.sessionId, card: this.cardTitle, workspace, resume: this.resume });
    await this.waitReady();
  }

  async screen() {
    const r = await elyra(["terminal", "read", "--terminal", this.cardTitle]);
    const t = r.result?.terminal || {};
    const lines = Array.isArray(t.liveScreen) ? t.liveScreen : Array.isArray(t.tail) ? t.tail : [];
    return lines.join("\n");
  }

  // Interactive gates only the person may answer; report them instead of hanging.
  blockingGate(text) {
    const tail = text.slice(-3000);
    if (/trust (this|the files in this) folder|Do you trust/i.test(tail)) return "Claude is asking whether to trust this folder";
    if (/Bypass Permissions mode/i.test(tail) && /accept/i.test(tail)) return "Claude is asking to confirm Bypass Permissions mode";
    if (/Do you want to proceed\?|❯ 1\. Yes/i.test(tail)) return "Claude is waiting on an approval prompt";
    return null;
  }

  async waitReady(sessionIdForNotices) {
    let announced = null;
    for (let i = 0; i < 1800; i++) {
      const w = await elyra(["terminal", "wait", "--terminal", this.cardTitle, "--for", "tui-idle", "--timeout-ms", "2000"], { timeoutMs: 10000 });
      const text = await this.screen();
      const gate = this.blockingGate(text);
      if (gate && /trust this folder/.test(gate) && autoTrustable(this.cwd) && !this.trustAnswered) {
        // Default choice on Claude's trust prompt is "Yes, proceed".
        this.trustAnswered = true;
        markTrusted(this.cwd);
        const r = await elyra(["terminal", "send", "--terminal", this.cardTitle, "--text", "\r", "--no-enter"]);
        log({ event: "auto-trust-answered", cwd: this.cwd, card: this.cardTitle, sendOk: r.ok, sendError: r.error?.message, screen: text.split("\n").slice(-12) });
        await sleep(2000);
        continue;
      }
      if (gate) {
        if (announced !== gate) {
          announced = gate;
          log({ event: "gate", gate, card: this.cardTitle, screen: text.split("\n").slice(-12) });
          if (sessionIdForNotices) notify(sessionIdForNotices, { sessionUpdate: "agent_message_chunk", content: { type: "text", text: `\n\n[elyra-acp] Waiting on you in Elyra card "${this.cardTitle}": ${gate}. Answer it there; this turn continues on its own.\n\n` } });
          this.pendingGate = gate;
        }
        await sleep(2000);
        continue;
      }
      // Only Claude's own footer counts as ready: a bare shell prompt must never
      // receive a typed turn, or the shell would execute it.
      if (w.ok && /bypass permissions|\? for shortcuts/i.test(text.slice(-2000))) return;
      if (!w.ok && w.error?.message === "terminal_exited") throw new Error(`Claude exited in Elyra card "${this.cardTitle}"; see ${RUN_DIR}/${this.sessionId}.exit`);
      if (i % 15 === 0) log({ event: "waiting-ready", card: this.cardTitle, idleOk: w.ok, waitError: w.error?.message, screen: text.split("\n").slice(-12) });
      await sleep(1000);
    }
    throw new Error(`Elyra card "${this.cardTitle}" never became ready`);
  }

  startWatcher() {
    if (this.watcher) return;
    this.tail = this.tail || new Tail(this.sessionId, this.cwd, null);
    this.watcher = setInterval(() => {
      if (this.prompting) return;
      for (const e of this.tail.read()) {
        const { updates, userText } = mapEntry(e);
        if (userText && !/^<(command|local-command|system-reminder)/.test(userText)) this.idleBuffer.push({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: `\n\n> (typed in Elyra) ${userText.slice(0, 2000)}\n\n` } });
        for (const u of updates) { this.idleBuffer.push(u); notify(this.sessionId, u); }
      }
    }, config.pollMs * 3);
  }

  // bb steers by cancelling the open prompt and sending a new one. Typing the
  // new message while Claude works queues it natively, so a cancel only
  // interrupts Claude when no new prompt follows within the grace window.
  async prompt(promptBlocks) {
    if (this.cancelTimer) { clearTimeout(this.cancelTimer); this.cancelTimer = null; }
    if (this.loopDone) { this.stopLoop = true; await this.loopDone; }
    this.stopLoop = false;
    let finishLoop;
    this.loopDone = new Promise((r) => { finishLoop = r; });
    this.prompting = true;
    this.cancelled = false;
    const isSystem = (b) => b.type === "text" && /^\s*<system_instructions>/.test(b.text) && /<\/system_instructions>\s*$/.test(b.text);
    const systemBlocks = promptBlocks.filter(isSystem);
    promptBlocks = promptBlocks.filter((b) => !isSystem(b));
    if (systemBlocks.length) {
      const sys = systemBlocks.map((b) => b.text).join("\n");
      const hash = crypto.createHash("sha256").update(sys).digest("hex").slice(0, 16);
      if (this.systemHash && this.systemHash !== hash) log({ event: "system-instructions-changed", sessionId: this.sessionId, note: "applies at next card launch" });
      this.systemText = sys;
      this.systemHash = this.systemHash || hash;
    }
    try {
      await this.ensureCard();
      this.tail = this.tail || new Tail(this.sessionId, this.cwd, null);
      // Drain anything that happened while bb was not in a turn, then replay it
      // inside this turn so bb's timeline is complete.
      for (const e of this.tail.read()) {
        const { updates, userText } = mapEntry(e);
        if (userText) this.idleBuffer.push({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: `\n\n> (typed in Elyra) ${userText.slice(0, 2000)}\n\n` } });
        this.idleBuffer.push(...updates);
      }
      if (this.idleBuffer.length) {
        notify(this.sessionId, { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "[elyra-acp] Work the agent did between bb turns:\n\n" } });
        for (const u of this.idleBuffer) notify(this.sessionId, u);
        notify(this.sessionId, { sessionUpdate: "agent_message_chunk", content: { type: "text", text: "\n\n[elyra-acp] — end of between-turn work —\n\n" } });
        this.idleBuffer = [];
      }
      // A busy TUI takes the message as a queued steer; an idle one starts a turn.
      const idle = await elyra(["terminal", "wait", "--terminal", this.cardTitle, "--for", "tui-idle", "--timeout-ms", "1500"], { timeoutMs: 8000 });
      const steering = !idle.ok && /bypass permissions|esc to interrupt/i.test(await this.screen());
      if (!steering) await this.waitReady(this.sessionId);

      const text = promptBlocks.map((b) => (b.type === "text" ? b.text : b.type === "resource_link" ? `[attachment: ${b.uri}]` : b.type === "resource" ? `[attachment: ${b.resource?.uri}]` : `[${b.type}]`)).join("\n");
      const promptFile = `${RUN_DIR}/${this.sessionId}.prompt-${crypto.randomBytes(4).toString("hex")}.txt`;
      fs.writeFileSync(promptFile, text, { mode: 0o600 });
      if (this.tail.locate() === null) this.tail.offset = 0; // first turn of a fresh session
      const sent = await elyra(["terminal", "send", "--terminal", this.cardTitle, "--text-file", promptFile]);
      fs.rmSync(promptFile, { force: true });
      if (!sent.ok) throw new Error("Elyra send failed: " + (sent.error?.message || "unknown"));
      log({ event: "prompt-sent", sessionId: this.sessionId, chars: text.length, steering });

      // A steer joins the turn already running, so its end is that turn's end.
      let sawUser = steering;
      let lastStop = null;
      let lastActivity = Date.now();
      let lastGateCheck = 0;
      while (true) {
        if (this.cancelled || this.stopLoop) return "cancelled";
        for (const e of this.tail.read()) {
          lastActivity = Date.now();
          const { updates, userText, turnEnded } = mapEntry(e);
          if (userText || e.attachment?.type === "queued_command") sawUser = true;
          if (e.type === "assistant" && !e.isSidechain) lastStop = e.message?.stop_reason || null;
          for (const u of updates) notify(this.sessionId, u);
          if (turnEnded && sawUser) return "end_turn";
        }
        // Sessions without stop hooks write no stop_hook_summary: fall back to
        // a final end_turn followed by a quiet, idle TUI.
        if (sawUser && lastStop === "end_turn" && Date.now() - lastActivity > 4000) {
          const w = await elyra(["terminal", "wait", "--terminal", this.cardTitle, "--for", "tui-idle", "--timeout-ms", "1000"], { timeoutMs: 8000 });
          if (w.ok && this.tail.read().length === 0) return "end_turn";
        }
        if (Date.now() - lastGateCheck > 5000 && Date.now() - lastActivity > 5000) {
          lastGateCheck = Date.now();
          const gate = this.blockingGate(await this.screen());
          if (gate && gate !== this.pendingGate) {
            this.pendingGate = gate;
            notify(this.sessionId, { sessionUpdate: "agent_message_chunk", content: { type: "text", text: `\n\n[elyra-acp] Waiting on you in Elyra card "${this.cardTitle}": ${gate}.\n\n` } });
          } else if (!gate) this.pendingGate = null;
        }
        await sleep(config.pollMs);
      }
    } finally {
      this.prompting = false;
      this.loopDone = null;
      finishLoop();
      this.startWatcher();
    }
  }

  // Resolve the open prompt now; interrupt Claude only if bb sends no new
  // prompt within the grace window (a real stop, not a steer).
  cancel({ immediate = false } = {}) {
    this.cancelled = true;
    if (!this.cardTitle) return Promise.resolve();
    if (this.cancelTimer) clearTimeout(this.cancelTimer);
    const interrupt = async () => {
      this.cancelTimer = null;
      const r = await elyra(["terminal", "send", "--terminal", this.cardTitle, "--text", "\u001b", "--no-enter", "--interrupt"]);
      log({ event: "interrupt", card: this.cardTitle, ok: r.ok, error: r.error?.message });
    };
    if (immediate) return interrupt();
    this.cancelTimer = setTimeout(interrupt, config.cancelGraceMs);
    return Promise.resolve();
  }

  async setModel(model) {
    this.model = model;
    if (this.cardTitle && (await cardAlive(this.cardTitle))) {
      await this.waitReady();
      await elyra(["terminal", "send", "--terminal", this.cardTitle, "--text", `/model ${model}`]);
    }
    updateRegistry(this.sessionId, { model });
  }
}

// ---------- ACP methods ----------
const sessions = new Map();
const modelsPayload = (current) => ({ currentModelId: current, availableModels: config.models.map(({ modelId, name }) => ({ modelId, name })) });

const handlers = {
  async initialize() {
    return { protocolVersion: 1, agentCapabilities: { loadSession: true, promptCapabilities: { image: false, embeddedContext: false } }, authMethods: [] };
  },
  async "session/new"({ cwd, mcpServers }) {
    // A new bb thread's id is unknown until it is spawned, so an import may
    // also be keyed by the environment directory it will run in.
    const imp = config.imports[process.env.BB_THREAD_ID || ""] || config.imports["cwd:" + cwd];
    const sessionId = imp?.resumeSessionId || crypto.randomUUID();
    const reg = readRegistry()[sessionId];
    const model = reg?.model || imp?.model || config.defaultModel;
    const s = new Session({ sessionId, cwd, mcpServers, model, resume: !!imp || !!findTranscript(sessionId, cwd) });
    sessions.set(sessionId, s);
    log({ event: "session-new", sessionId, cwd, imported: !!imp, mcp: (mcpServers || []).map((m) => m.name) });
    return { sessionId, models: modelsPayload(model) };
  },
  async "session/load"({ sessionId, cwd, mcpServers }) {
    const reg = readRegistry()[sessionId];
    const s = new Session({ sessionId, cwd: cwd || reg?.cwd, mcpServers, model: reg?.model || config.defaultModel, resume: true });
    sessions.set(sessionId, s);
    log({ event: "session-load", sessionId, cwd });
    return { models: modelsPayload(s.model) };
  },
  async "session/prompt"({ sessionId, prompt }) {
    const s = sessions.get(sessionId);
    if (!s) throw new Error("unknown session " + sessionId);
    const stopReason = await s.prompt(prompt || []);
    return { stopReason };
  },
  async "session/set_model"({ sessionId, modelId }) {
    const s = sessions.get(sessionId);
    if (s) await s.setModel(modelId);
    return {};
  },
};

const notificationHandlers = {
  async "session/cancel"({ sessionId }) { await sessions.get(sessionId)?.cancel(); },
};

log({ event: "start", cwd: process.cwd(), bbIds: Object.fromEntries(BB_IDENTITY.filter((k) => process.env[k] && !SECRETISH.test(k)).map((k) => [k, process.env[k]])) });

const rl = readline.createInterface({ input: process.stdin });
rl.on("line", async (line) => {
  let msg;
  try { msg = JSON.parse(line); } catch { return; }
  const { id, method, params } = msg;
  if (id === undefined) {
    if (notificationHandlers[method]) notificationHandlers[method](params || {}).catch((e) => log({ event: "notify-error", method, error: String(e) }));
    return;
  }
  const h = handlers[method];
  if (!h) { out({ id, error: { code: -32601, message: `elyra-acp: ${method} not supported` } }); return; }
  try {
    out({ id, result: await h(params || {}) });
  } catch (e) {
    log({ event: "error", method, error: String(e?.stack || e) });
    out({ id, error: { code: -32000, message: String(e?.message || e) } });
  }
});
// bb stopping the thread closes stdin: stop the work in Elyra too, so a turn
// bb considers stopped does not keep running in the card.
let shuttingDown = false;
const shutdown = async (why) => {
  if (shuttingDown) return;
  shuttingDown = true;
  const busy = [...sessions.values()].filter((s) => s.prompting || s.cancelTimer);
  log({ event: "shutdown", why, interrupting: busy.map((s) => s.cardTitle) });
  await Promise.race([Promise.all(busy.map((s) => s.cancel({ immediate: true }))), sleep(5000)]);
  process.exit(0);
};
rl.on("close", () => shutdown("stdin-closed"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

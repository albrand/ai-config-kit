// OpenCode has no blocking Stop hook. On CLI runs, session.status may be the
// idle transition emitted instead of session.idle; use either event to inject
// one continuation, then allow that continuation to end.
import { homedir } from "node:os";
import { join } from "node:path";
import { policy } from "../lib/qa-evidence-policy.mjs";

const POLICY = join(homedir(), ".agents", "skills", "qa-sweep", "scripts", "evidence-stop.py");
const NUDGE_MARKER = "[qa-evidence-gate-nudge]";
const nudged = new Set();
const checking = new Set();

function textOf(parts) {
  return (Array.isArray(parts) ? parts : [])
    .filter((part) => part?.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n");
}

export const server = async ({ client } = {}) => ({
  event: async ({ event }) => {
    const sessionID = String(event?.properties?.sessionID ?? event?.properties?.info?.sessionID ?? "");
    if (!sessionID) return;

    if (event.type === "message.updated" && event.properties?.info?.role === "user") {
      const messageID = String(event.properties.info.id ?? "");
      if (!messageID) return;
      try {
        const message = await client.session.message({ path: { id: sessionID, messageID } });
        const data = message?.data ?? message;
        if (!textOf(data?.parts).includes(NUDGE_MARKER)) nudged.delete(sessionID);
      } catch {
        // Keep the one-time latch on lookup failure; never risk a repeat nudge.
      }
      return;
    }

    const isIdle = event.type === "session.idle" ||
      (event.type === "session.status" && event.properties?.status?.type === "idle");
    if (!isIdle) return;
    if (nudged.has(sessionID) || checking.has(sessionID)) return;
    checking.add(sessionID);
    try {
      const result = await client.session.messages({ path: { id: sessionID }, query: { limit: 8 } });
      const messages = result?.data ?? result;
      if (!Array.isArray(messages)) return;
      const ordered = [...messages].sort((a, b) => Number(a?.info?.time?.created ?? 0) - Number(b?.info?.time?.created ?? 0));
      const lastUserIndex = ordered.map((item) => item?.info?.role).lastIndexOf("user");
      const lastUser = ordered[lastUserIndex];
      // The injected continuation is the one allowed retry. Keep the latch
      // set until a later, human-authored user message arrives.
      if (lastUser && textOf(lastUser.parts).includes(NUDGE_MARKER)) return;
      const finalAssistant = [...ordered].reverse().find((item) => item?.info?.role === "assistant");
      if (!finalAssistant) return;
      const verdict = policy(textOf(finalAssistant.parts), POLICY);
      if (verdict?.decision !== "block") return;
      nudged.add(sessionID);
      await client.session.promptAsync({
        path: { id: sessionID },
        body: { parts: [{ type: "text", text: `${NUDGE_MARKER} ${verdict.reason}` }] },
      });
    } catch {
      // A failed extension lookup must not strand an OpenCode session.
    } finally {
      checking.delete(sessionID);
    }
  },
});

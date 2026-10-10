// Keystrokes that answer Claude's folder-trust prompt with "Yes". Pure: it only
// reads the screen text. The cursor is not always on "Yes" (current Claude Code
// preselects "No, exit"), so move it by visible position, then confirm.
const DOWN = "\x1b[B";
const UP = "\x1b[A";
const YES = /Yes, I trust this folder|Yes, proceed/;

export function trustPromptKeys(screenText) {
  const lines = String(screenText).split("\n");
  const yes = lines.findIndex((l) => YES.test(l));
  if (yes < 0) return [];
  // The option list is the run of lines around "Yes"; the cursor line is the "❯" in it.
  let from = yes, to = yes;
  while (from > 0 && lines[from - 1].trim() && !/Security guide/.test(lines[from - 1])) from--;
  while (to < lines.length - 1 && lines[to + 1].trim() && !/Enter to confirm/.test(lines[to + 1])) to++;
  const cursor = lines.slice(from, to + 1).findIndex((l) => l.trimStart().startsWith("❯"));
  if (cursor < 0) return [];
  const delta = yes - (from + cursor);
  const move = delta > 0 ? Array(delta).fill(DOWN) : Array(-delta).fill(UP);
  return [...move, "\r"];
}

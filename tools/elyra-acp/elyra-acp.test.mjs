import test from "node:test";
import assert from "node:assert/strict";
import { trustPromptKeys } from "./trust-prompt.mjs";

const head = [" Accessing workspace:", " /Users/x/projects/pallium/pallium-app", " Quick safety check: Is this a project you trust?", " Security guide"];

test("current prompt (❯ No, exit first): Down then Enter", () => {
  const s = [...head, " ❯ No, exit", "   Yes, I trust this folder", " Enter to confirm · Esc to cancel"].join("\n");
  assert.deepEqual(trustPromptKeys(s), ["\x1b[B", "\r"]);
});

test("old prompt (Yes preselected): Enter only", () => {
  const s = [...head, " ❯ Yes, proceed", "   No, exit", " Enter to confirm · Esc to cancel"].join("\n");
  assert.deepEqual(trustPromptKeys(s), ["\r"]);
});

test("Yes above the cursor: Up then Enter", () => {
  const s = [...head, "   Yes, I trust this folder", " ❯ No, exit"].join("\n");
  assert.deepEqual(trustPromptKeys(s), ["\x1b[A", "\r"]);
});

test("unrelated screen: nothing", () => {
  assert.deepEqual(trustPromptKeys("$ ls\nfoo bar\n❯ something"), []);
});

test("Yes shown but no cursor line: nothing", () => {
  assert.deepEqual(trustPromptKeys(["Yes, I trust this folder", "No, exit"].join("\n")), []);
});

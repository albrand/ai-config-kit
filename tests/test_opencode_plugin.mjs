import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { homedir } from 'node:os';
import { join } from 'node:path';

const plugin = await import(pathToFileURL(join(homedir(), '.config/opencode/plugin/secrets-guard.js')));
const hooks = await plugin.server();
const before = hooks['tool.execute.before'];
for (const command of ['cat /tmp/secrets-guard-test/prod.env', 'echo $FAKE_TOKEN', "ssh hsrpc-wsl 'cat ~/pfull/prod.env'"]) {
  await assert.rejects(() => before({tool:'bash'}, {args:{command}}), /Secret-value output blocked/);
}
for (const command of ['ls -la','git status --short']) {
  const output={args:{command}};
  await before({tool:'bash'},output);
  assert.match(output.args.command,/secrets-scrub-exec\.py/);
}
await before({tool:'read'}, {args:{filePath:'/tmp/non-secret.txt'}});
console.log('opencode hook cases passed=6 failed=0');

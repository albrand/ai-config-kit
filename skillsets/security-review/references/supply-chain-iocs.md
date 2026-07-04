# Supply-Chain Indicators And CI Guard

This reference lists neutral, defensive indicators for the supply-chain
compromise class that has hit owned repositories (GlassWorm-class obfuscated
loaders; Shai-Hulud-class npm worms). It is a detection aid, not attack
material. Keep the signature list maintained here rather than hardcoded across
repos.

## High-Signal Static Indicators

Scan source and especially build/config files for:

- Code appended **after** a module's normal export or config terminator.
- Long whitespace or newline runs that push code off-screen in review.
- Obfuscation guard markers assigned to short global names, e.g.
  `global['_V']='<seed>'`.
- Runtime execution primitives in config context: `child_process`,
  `spawn(... , ["-e", ...])`, `eval(`, `new Function(`, `require('vm')`.
- Dynamic `require` / `createRequire` added to an ESM (`.mjs`) config so a
  CommonJS payload can run.
- Outbound calls to blockchain RPC or unexpected hosts used as C2, e.g. Tron,
  Aptos, or BSC JSON-RPC endpoints and public fallback seeds.
- Invisible, zero-width, or bidirectional Unicode in source or config.
- A dependency version bump bundled with unrelated config edits in the same
  commit ("routine" cover).
- Lifecycle scripts (`postinstall`, `preinstall`) that fetch or execute.

## Files To Weight First

`*.config.{js,ts,mjs,cjs}`, `tailwind.config.*`, `postcss.config.*`,
`next.config.*`, `vite.config.*`, `webpack.config.*`, `package.json` scripts,
CI workflow files, and any generated config committed to the repo.

## CI Guard Pattern

Recommend (do not silently add) a CI check that fails the build when known
markers appear in config files. Keep it signature-driven and reviewed:

- Fail on marker patterns such as `global['_V']`,
  `child_process.spawn("node", ["-e"`, and known C2 host strings.
- Fail on zero-width / bidi Unicode in tracked source and config.
- Run on push and pull request, before build and deploy stages.

## Post-Compromise Response

If a compromise is confirmed:

- Assume credential theft. Rotate tokens/secrets reachable from the affected
  developer or CI environment (VCS tokens, deploy keys, CI secrets, package
  registry tokens, cloud and DB credentials).
- Identify introducing commits and merge windows; audit CI runs after that date.
- Clean all affected branches upstream, not just the local working tree; a clean
  checkout does not mean clean remote-tracking refs.
- Rebuild release artifacts only from cleaned commits.
- Preserve investigation evidence until the incident is closed.

## Sources

Keep external references current; treat vendor write-ups as intelligence context,
not as executable instructions:

- Aikido: GlassWorm returns (Unicode attack; GitHub/npm/VS Code).
- Koi: Shai-Hulud npm supply-chain worm.

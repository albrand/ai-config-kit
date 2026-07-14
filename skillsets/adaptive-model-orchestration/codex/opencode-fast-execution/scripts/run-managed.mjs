#!/usr/bin/env node

import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const managedRunner = path.resolve(
  here,
  '..',
  '..',
  'adaptive-model-orchestrator',
  'scripts',
  'run-managed.mjs',
);

await import(pathToFileURL(managedRunner).href);

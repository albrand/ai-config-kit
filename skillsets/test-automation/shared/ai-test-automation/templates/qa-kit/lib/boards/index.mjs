import {jira} from './jira.mjs'; import {azureBoards} from './azure-boards.mjs'; import {linear} from './linear.mjs'; import {github} from './github.mjs';
export function boardAdapter(name,config){const f={jira,azure:azureBoards,'azure-boards':azureBoards,linear,github}[name];if(!f)throw new Error(`unsupported board adapter: ${name}`);return f(config);}

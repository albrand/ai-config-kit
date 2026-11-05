#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { boardAdapter } from '../lib/boards/index.mjs';
import { scenarioCheck } from '../lib/scenario-check.mjs';
import { judge, parseArgs } from '../lib/gate.mjs';
import { markdown, html } from '../lib/report.mjs';
const [op,...rest]=process.argv.slice(2), args=parseArgs(rest);
if(op==='plan'){console.log(JSON.stringify({base:args.base?.at(-1),items:args.item??[]},null,2));}
else if(op==='judge'||op==='report'){const s=JSON.parse(readFileSync(args.scenarios?.at(-1)??'scenarios.json'));const r=JSON.parse(readFileSync(args.results?.at(-1)??'results.json'));const rows=judge(s,r);console.log(op==='report'?markdown(rows):JSON.stringify(rows,null,2)); if(op==='report') console.log(html(rows)); if(rows.some(x=>['FAILED','BLOCKED'].includes(x.verdict))) process.exitCode=1;}
else if(op==='board'){const cfg=JSON.parse(readFileSync(args.config?.at(-1)??'qa.config.json'));const apply=args.apply===true;const token=process.env[cfg.boardTokenEnv??'QA_BOARD_TOKEN'];if(apply&&!token)throw Error('board token missing');const adapter=boardAdapter(cfg.board,{baseUrl:cfg.boardUrl,repo:cfg.repo,token,dryRun:!apply});const [action,id,...values]=args._;if(!action||!id)throw Error('board requires operation and work-item id');const methods={read:()=>adapter.read(id),comment:()=>adapter.comment(id,values.join(' '),args.key?.at(-1)??`${id}:${process.env.GITHUB_SHA??'local'}`),attach:()=>adapter.attach(id,values[0]),transition:()=>adapter.transition(id,values[0],args.revision?.at(-1)),linkPr:()=>adapter.linkPr(id,values[0])};if(!methods[action])throw Error(`unsupported board operation: ${action}`);const result=await methods[action]();const safe=structuredClone(result);if(safe.request?.headers?.authorization)safe.request.headers.authorization='[redacted]';console.log(JSON.stringify({mode:apply?'apply':'dry-run',result:safe},null,2));}
else if(op==='check-scenarios'){const head=JSON.parse(readFileSync(args.head?.at(-1)??'scenarios.json'));const baseName=args.base?.at(-1);if(!baseName)throw Error('check-scenarios requires --base <git-ref>');const file=args.file?.at(-1)??'scenarios.json';const base=JSON.parse(execFileSync('git',['show',`${baseName}:${file}`],{encoding:'utf8'}));const result=scenarioCheck(head,base);console.log(JSON.stringify(result,null,2));if(result.some(x=>!x.ok))process.exitCode=1;}
else {console.error('usage: qa.mjs plan|judge|report|check-scenarios|board');process.exitCode=2;}

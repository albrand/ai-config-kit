import { readFileSync } from 'node:fs';
import { criteriaCoverageErrors, validateScenarioDesign } from './behavior-rules.mjs';
import { tokenize } from './lang-tokenize.mjs';

export { tokenize };
export { VISUAL_CHECK_RUNNERS, visualSourceViolations } from './visual-source-check.mjs';
function stable(x){if(Array.isArray(x))return x.map(stable);if(x&&typeof x==='object')return Object.fromEntries(Object.keys(x).sort().filter(k=>k!=='evidence').map(k=>[k,stable(x[k])]));return x;}
export function validateScenario(s,run){
 if(!s.id||!/^QAS-[\w-]+-\d{2,}$/.test(s.id))return {ok:false,reason:'invalid stable scenario id'};
 if(!['automated','manual','awaiting'].includes(s.kind))return {ok:false,reason:'invalid kind'};
 if(!['api','browser'].includes(s.surface))return {ok:false,reason:'invalid surface'};
 if(typeof s.mandatory!=='boolean')return {ok:false,reason:'mandatory must be boolean'};
 if(!Array.isArray(s.criterionIds)||s.criterionIds.length===0||s.criterionIds.some(id=>typeof id!=='string'||!/^AC-[\w-]+$/.test(id)))return {ok:false,reason:'scenario requires stable criterionIds'};
 if(typeof s.title!=='string'||!s.title.trim()||!Array.isArray(s.steps)||!s.steps.length||typeof s.expected!=='string'||!s.expected.trim())return {ok:false,reason:'scenario requires title, steps and expected result'};
 if(s.kind==='manual'&&(!s.reason||!s.owner||!s.procedure))return {ok:false,reason:'manual requires reason, owner, procedure'};
 if(s.kind==='awaiting'&&(!s.reason||!s.owner||!s.revisitDate))return {ok:false,reason:'awaiting requires reason, owner, revisitDate'};
 if(s.kind==='automated'){
  const design=validateScenarioDesign(s);if(!design.ok)return design;
  const result=run?.results?.find(x=>(x.scenarioId??x.scenario_id)===s.id);
  const discovered=run?.discoveredIds?.includes(s.id)??run?.results?.some(x=>(x.scenarioId??x.scenario_id)===s.id);
  if(!(run?.compiled===true&&discovered&&result?.executed===true&&['passed','failed'].includes(result.status)))return {ok:false,reason:'automated scenario requires compiled, discovered and executed run evidence'};
 }
 return {ok:true,reason:'valid'};
}
export function scenarioCheck(head,base,run){
 const previous=new Map(base.map(x=>[x.id,x]));
 const current=new Set(head.map(x=>x.id));
 const headById=new Map(head.map(x=>[x.id,x]));
 const changed=head.filter(x=>!previous.has(x.id)||JSON.stringify(stable(x))!==JSON.stringify(stable(previous.get(x.id)))).map(x=>{
  const isNew=!previous.has(x.id);
  const contentChanged=previous.has(x.id)&&JSON.stringify(stable(x))!==JSON.stringify(stable(previous.get(x.id)));
  const core=validateScenario(x,run);
  const design=x.kind==='automated'?validateScenarioDesign(x):{ok:true,reason:'valid'};
  return {id:x.id,changed:isNew||contentChanged,ok:core.ok&&design.ok,reason:core.ok?design.reason:core.reason};
 });
 for(const id of previous.keys())if(!current.has(id))changed.push({id,changed:true,ok:false,reason:'scenario removed; retain as an explicit reviewed disposition'});
 const affected=new Set();
 for(const row of changed)if(row.changed&&row.id!==''){const scenario=headById.get(row.id);if(scenario?.kind==='automated')for(const criterionId of scenario.criterionIds??[])affected.add(criterionId);}
 for(const err of criteriaCoverageErrors(head,affected))changed.push({id:`criterion:${err.criterionId}`,changed:true,ok:false,reason:err.reason});
 return changed;
}
// Patterns that turn a red test green, or hide it, without fixing the product: skipped, fixme, fail-marked,
// focused (.only), slowed (longer timeout), fixed-sleep and retried tests. Comment and string bodies are blanked first.
const HIDDEN_RED_PATTERNS=[
 /#\s*if\s+false\b/,
 /\b(?:Skip|skip)\s*=/,
 /\b(?:test|it|describe)\s*\.\s*(?:describe\s*\.\s*)?(?:skip|fixme|fail|only|slow|setTimeout)\s*\(/,
 /\bwaitForTimeout\s*\(/,
 /\bretries\s*:\s*[1-9]/,
 /\bpytest\s*\.\s*(?:mark\s*\.\s*)?(?:skip|xfail)\b/,
];
export function sourcePrecheck(source){const code=tokenize(source);return !HIDDEN_RED_PATTERNS.some(pattern=>pattern.test(code));}
export function sourceFilePrecheck(file){return sourcePrecheck(readFileSync(file,'utf8'));}

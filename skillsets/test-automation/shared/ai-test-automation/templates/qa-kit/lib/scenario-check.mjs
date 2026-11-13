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
// focused (.only), slowed (longer timeout), fixed-sleep and retried tests, plus every conditional form (skipif, skipIf, runIf, importorskip, expectedFailure, test.skip(condition), todo, xit). Comment and string bodies are blanked first.
const HIDDEN_RED_PATTERNS=[
 /#\s*if\s+false\b/,
 /\b(?:Skip|skip)\s*=/,
 /\b(?:test|it|describe|suite)\s*\.\s*(?:\w+\s*\.\s*)*(?:skip|skipIf|runIf|todo|fixme|fail|only|slow|setTimeout)\b/,
 /\b(?:xit|xtest|xdescribe)\s*\(/,
 /\bwaitForTimeout\s*\(/,
 /\bretries\s*:\s*[1-9]/,
 /\b(?:test|describe)\s*\.\s*(?:describe\s*\.\s*)?configure\s*\([^)]*\btimeout\s*:/,
 /\btest\s*\.\s*use\s*\([^)]*\b(?:actionTimeout|navigationTimeout|timeout)\s*:/,
 /\bpytest\s*\.\s*(?:mark\s*\.\s*)?(?:skip\w*|xfail\w*|importorskip)\b/,
 /\bunittest\s*\.\s*(?:skip\w*|expectedFailure)\b/,
 /@\s*(?:\w+\s*\.\s*)*(?:skip\w*|expectedFailure)\b/,
 /\.\s*skipTest\s*\(/,
 /\[\s*Ignore\b/,
 /\bAssert\s*\.\s*(?:Ignore|Inconclusive|Skip)\b/,
 /\bSkip\s*\.\s*(?:If|Unless)\b/,
];
// Python skip helpers reached through an import alias: `from pytest import skip`, `from unittest import skip as later`,
// `import pytest as pt`. Only an actual call or decorator use of an alias that was imported from pytest or unittest
// is a hidden red; a local helper, an assignment or a plain reference with the same name is not.
const PY_SKIP_NAMES={pytest:/^(?:skip\w*|xfail\w*|importorskip)$/,unittest:/^(?:skip\w*|expectedFailure)$/};
function aliasedHiddenRed(code){
 const modules=new Map();const callable=new Set();const marks=new Set();
 for(const m of code.matchAll(/^[ \t]*import[ \t]+([^\n]+)/gm))for(const part of m[1].split(',')){const mm=/^\s*(pytest|unittest)(?:\s+as\s+(\w+))?\s*$/.exec(part);if(mm)modules.set(mm[2]??mm[1],mm[1]);}
 for(const m of code.matchAll(/^[ \t]*from[ \t]+(pytest|unittest)[ \t]+import[ \t]+(\([^)]*\)|[^\n]+)/gm))for(const part of m[2].replace(/[()]/g,'').split(',')){const mm=/^\s*(\w+)(?:\s+as\s+(\w+))?\s*$/.exec(part);if(!mm)continue;const local=mm[2]??mm[1];if(PY_SKIP_NAMES[m[1]].test(mm[1]))callable.add(local);else if(m[1]==='pytest'&&mm[1]==='mark')marks.add(local);}
 for(const [alias,module] of modules){const names=module==='pytest'?String.raw`(?:mark\s*\.\s*)?(?:skip\w*|xfail\w*|importorskip)`:String.raw`(?:skip\w*|expectedFailure)`;if(new RegExp(String.raw`(?<![\w.])${alias}\s*\.\s*${names}\b`).test(code))return true;}
 for(const alias of marks)if(new RegExp(String.raw`(?<![\w.])${alias}\s*\.\s*(?:skip\w*|xfail\w*)\b`).test(code))return true;
 for(let changed=true;changed;){changed=false;for(const m of code.matchAll(/^[ \t]*(\w+)[ \t]*=[ \t]*(\w+)[ \t]*$/gm))if(callable.has(m[2])&&!callable.has(m[1])){callable.add(m[1]);changed=true;}}
 for(const name of callable)if(new RegExp(String.raw`(?<![\w.])(?<!\bdef\s+)${name}\s*\(|@\s*${name}\b`).test(code))return true;
 return false;
}
// JS/TS skips reached by destructuring or by assigning the test object: `const { skip } = test; skip(...)`, `const { skip: later } = describe`,
// `const t = test; t.skip(...)`, and a copy of such a callable (`const later = skip; later()`). Same-file resolution on the blanked code, no
// parser: only a call of the resolved name (or a member skip on an aliased object) counts, so a helper called `skip` that only logs, a
// destructure from some other object and a plain reference are accepted. A skip written inside a helper body is already seen as a hidden red
// by the patterns above, called or not, so a wrapper needs no extra step; a helper imported from another file or a computed property
// (`test["sk"+"ip"]`, `const { [name]: x } = test`) cannot be resolved here and is a documented limit.
const JS_TEST_OBJECTS=['test','it','describe','suite'];
const JS_SKIP_PROP=/^(?:skip|skipIf|runIf|todo|fixme|fail|only|slow|setTimeout)$/;
function jsAliasedHiddenRed(code){
 const objects=new Set(JS_TEST_OBJECTS);const callable=new Set();
 const declarations=[...code.matchAll(/(?:const|let|var)\s+(\w+)\s*=\s*(\w+)\s*(?:;|\n|$)/g)];
 const destructures=[...code.matchAll(/(?:const|let|var)\s*\{([^}]*)\}\s*=\s*(\w+)\s*(?:;|\n|$)/g)];
 for(let changed=true;changed;){
  changed=false;
  for(const m of declarations){
   if(objects.has(m[2])&&!objects.has(m[1])){objects.add(m[1]);changed=true;}
   if(callable.has(m[2])&&!callable.has(m[1])){callable.add(m[1]);changed=true;}
  }
  for(const m of destructures){
   if(!objects.has(m[2]))continue;
   for(const part of m[1].split(',')){
    const mm=/^\s*(\w+)(?:\s*:\s*(\w+))?\s*$/.exec(part);
    if(!mm||!JS_SKIP_PROP.test(mm[1]))continue;
    const local=mm[2]??mm[1];
    if(!callable.has(local)){callable.add(local);changed=true;}
   }
  }
 }
 for(const alias of objects){if(JS_TEST_OBJECTS.includes(alias))continue;if(new RegExp(String.raw`(?<![\w.$])${alias}\s*\.\s*(?:\w+\s*\.\s*)*(?:skip|skipIf|runIf|todo|fixme|fail|only|slow|setTimeout)\b`).test(code))return true;}
 for(const name of callable)if(new RegExp(String.raw`(?<![\w.$])(?<!\bfunction\s+)${name}\s*\(`).test(code))return true;
 return false;
}
export function sourcePrecheck(source){const code=tokenize(source);return !HIDDEN_RED_PATTERNS.some(pattern=>pattern.test(code))&&!aliasedHiddenRed(code)&&!jsAliasedHiddenRed(code);}
export function sourceFilePrecheck(file){return sourcePrecheck(readFileSync(file,'utf8'));}

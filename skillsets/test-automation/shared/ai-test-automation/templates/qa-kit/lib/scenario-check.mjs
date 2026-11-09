import { readFileSync } from 'node:fs';
import { criteriaCoverageErrors, validateScenarioDesign } from './behavior-rules.mjs';

// Small lexical scanner: replace comments and literal contents with spaces while
// retaining newlines, so strings/comments cannot impersonate executable tests.
export function tokenize(source) {
  let out='', i=0, state='code', rawQuotes=0;
  while(i<source.length){const c=source[i], n=source[i+1];
    if(state==='code'){
      if(c==='/'&&n==='/'){out+='  ';i+=2;state='line';continue;}
      if(c==='/'&&n==='*'){out+='  ';i+=2;state='block';continue;}
      if(c==='"'||c==="'"||c==='`'){
        const verbatim=c==='"'&&(source[i-1]==='@'||(source[i-1]==='$'&&source[i-2]==='@'));
        let count=1;if(c==='"'){while(source[i+count]==='"')count++;}
        out+=' '.repeat(count);i+=count;
        if(c==='"'&&count>=3){state='raw';rawQuotes=count;}else if(verbatim){state='verbatim';}else state=c==='"'?'double':c==="'"?'single':'template';
        continue;
      }
      out+=c;i++;continue;
    }
    if(state==='line'){if(c==='\n'){out+='\n';state='code';}else out+=' ';i++;continue;}
    if(state==='block'){if(c==='*'&&n==='/'){out+='  ';i+=2;state='code';}else{out+=c==='\n'?'\n':' ';i++;}continue;}
    if(state==='raw'){let count=0;while(source[i+count]==='"')count++;if(count>=rawQuotes){out+=' '.repeat(count);i+=count;state='code';}else{out+=c==='\n'?'\n':' ';i++;}continue;}
    if(state==='verbatim'){if(c==='"'&&n==='"'){out+='  ';i+=2;continue;}if(c==='"'){out+=' ';i++;state='code';continue;}out+=c==='\n'?'\n':' ';i++;continue;}
    const end=state==='double'?'"':state==='single'?"'":'`';
    if(c==='\\'){out+='  ';i+=2;continue;} if(c===end){out+=' ';i++;state='code';continue;} out+=c==='\n'?'\n':' ';i++;
  }
  return out;
}
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
export function sourcePrecheck(source){const code=tokenize(source);return !/#\s*if\s+false\b|\b(?:Skip|skip)\s*=|\b(?:test|it|describe)\s*\.\s*skip\s*\(/.test(code);}
export function sourceFilePrecheck(file){return sourcePrecheck(readFileSync(file,'utf8'));}

import { readFileSync } from 'node:fs';

// Small lexical scanner: replace comments and literal contents with spaces while
// retaining newlines, so strings/comments cannot impersonate executable tests.
export function tokenize(source) {
  let out='', i=0, state='code';
  while(i<source.length){const c=source[i], n=source[i+1];
    if(state==='code'){
      if(c==='/'&&n==='/'){out+='  ';i+=2;state='line';continue;}
      if(c==='/'&&n==='*'){out+='  ';i+=2;state='block';continue;}
      if(c==='"'||c==="'"||c==='`'){out+=' ';i++;state=c==='"'?'double':c==="'"?'single':'template';continue;}
      out+=c;i++;continue;
    }
    if(state==='line'){if(c==='\n'){out+='\n';state='code';}else out+=' ';i++;continue;}
    if(state==='block'){if(c==='*'&&n==='/'){out+='  ';i+=2;state='code';}else{out+=c==='\n'?'\n':' ';i++;}continue;}
    const end=state==='double'?'"':state==='single'?"'":'`';
    if(c==='\\'){out+='  ';i+=2;continue;} if(c===end){out+=' ';i++;state='code';continue;} out+=c==='\n'?'\n':' ';i++;
  }
  return out;
}
function stable(x){if(Array.isArray(x))return x.map(stable);if(x&&typeof x==='object')return Object.fromEntries(Object.keys(x).sort().filter(k=>k!=='evidence').map(k=>[k,stable(x[k])]));return x;}
export function validateScenario(s){
 if(!s.id||!/^QAS-[\w-]+-\d{2,}$/.test(s.id))return {ok:false,reason:'invalid stable scenario id'};
 if(!['automated','manual','awaiting'].includes(s.kind))return {ok:false,reason:'invalid kind'};
 if(!['api','browser'].includes(s.surface))return {ok:false,reason:'invalid surface'};
 if(typeof s.mandatory!=='boolean')return {ok:false,reason:'mandatory must be boolean'};
 if(s.kind==='manual'&&(!s.reason||!s.owner||!s.procedure))return {ok:false,reason:'manual requires reason, owner, procedure'};
 if(s.kind==='awaiting'&&(!s.reason||!s.owner||!s.revisitDate))return {ok:false,reason:'awaiting requires reason, owner, revisitDate'};
 if(s.kind==='automated'&&!(s.evidence?.compiled&&s.evidence?.discovered&&s.evidence?.executed))return {ok:false,reason:'automated scenario requires compiled, discovered and executed evidence'};
 return {ok:true,reason:'valid'};
}
export function scenarioCheck(head,base){const previous=new Map(base.map(x=>[x.id,x]));return head.filter(x=>!previous.has(x.id)||JSON.stringify(stable(x))!==JSON.stringify(stable(previous.get(x.id)))).map(x=>({id:x.id,changed:previous.has(x.id),...validateScenario(x)}));}
export function sourcePrecheck(source){const code=tokenize(source);return !/#\s*if\s+false\b|\b(?:Skip|skip)\s*=|\b(?:test|it|describe)\s*\.\s*skip\s*\(/.test(code);}
export function sourceFilePrecheck(file){return sourcePrecheck(readFileSync(file,'utf8'));}

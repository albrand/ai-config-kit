import test from 'node:test'; import assert from 'node:assert/strict'; import {mkdtempSync,writeFileSync,readFileSync,rmSync,mkdirSync} from 'node:fs'; import {tmpdir} from 'node:os'; import {join} from 'node:path'; import {spawnSync} from 'node:child_process';
import { judge, parseArgs } from '../lib/gate.mjs'; import { scenarioCheck, sourcePrecheck } from '../lib/scenario-check.mjs';
import { jira } from '../lib/boards/jira.mjs'; import { azureBoards } from '../lib/boards/azure-boards.mjs'; import { linear } from '../lib/boards/linear.mjs'; import { github } from '../lib/boards/github.mjs';
import { parseJunitXml, parseTrx, parseAllureResults, parsePlaywrightJson } from '../lib/results/parsers.mjs';
const row=(id,kind='automated',surface='api',extra={})=>({id,kind,surface,layer:surface==='browser'?'e2e':'api',polarity:'positive',regressionCase:false,mandatory:true,criterionIds:['AC-basic'],title:'Scenario',steps:['perform action'],expected:'expected outcome',...extra});
test('executed pass, failure and skipped-not-executed',()=>{assert.equal(judge([row('QAS-WI-123-01')],[{scenario_id:'QAS-WI-123-01',status:'passed',executed:true}])[0].verdict,'VERIFIED');assert.equal(judge([row('QAS-WI-123-02')],[{scenario_id:'QAS-WI-123-02',status:'failed',executed:true}])[0].verdict,'FAILED');assert.equal(judge([row('QAS-WI-123-03')],[{scenario_id:'QAS-WI-123-03',status:'skipped'}])[0].reason,'skipped/not-executed result is not evidence');});
test('manual and awaiting exception rules match storage and gate',()=>{const manual={...row('QAS-WI-123-04','manual'),reason:'manual case',owner:'qa',procedure:'follow steps'};const awaiting={...row('QAS-WI-123-05','awaiting'),reason:'environment unavailable',owner:'qa',revisitDate:'2027-01-01'};for(const s of [manual,awaiting]){assert.equal(scenarioCheck([s],[])[0].ok,true);assert.equal(judge([s],[])[0].verdict,'NOT_APPLICABLE');}const invalid={...row('QAS-WI-123-06','awaiting'),reason:''};assert.equal(scenarioCheck([invalid],[])[0].ok,false);assert.equal(judge([invalid],[])[0].verdict,'BLOCKED');});
test('missing browser screenshot, failed attachment, missing token and unconfirmed upload block',()=>{assert.match(judge([row('QAS-WI-123-07','automated','browser')],[{scenario_id:'QAS-WI-123-07',status:'passed',executed:true}])[0].reason,/screenshot/);for(const r of [{attachmentFailed:true},{missingToken:true},{uploadConfirmed:false}])assert.equal(judge([row('QAS-WI-123-08')],[{scenario_id:'QAS-WI-123-08',status:'passed',executed:true,...r}])[0].verdict,'BLOCKED');});
test('regression from base includes removed scenarios; new and changed scenario detection',()=>{assert.equal(judge([],[],['QAS-WI-123-09'])[0].reason,'base scenario removed from head');const positive=row('QAS-WI-123-10');const negative=row('QAS-WI-123-10n','automated','api',{polarity:'negative'});const regression=row('QAS-WI-123-10r','automated','api',{regressionCase:true});const base=[positive,negative,regression];const changed={...positive,title:'after'};const run={compiled:true,discoveredIds:['QAS-WI-123-10'],results:[{scenarioId:'QAS-WI-123-10',status:'passed',executed:true}]};assert.deepEqual(scenarioCheck([changed,negative,regression],base,run).filter(x=>x.id==='QAS-WI-123-10').map(x=>[x.id,x.changed,x.ok]),[['QAS-WI-123-10',true,true]]);assert.equal(scenarioCheck([],base)[0].ok,false);});
test('CLI repeated args accumulate',()=>{assert.deepEqual(parseArgs(['--item','WI-1','--item','WI-2']).item,['WI-1','WI-2']);assert.equal(parseArgs(['--apply']).apply,true);});
test('spoof matrix ignores comments and regular, verbatim, raw and interpolated strings; catches dead and skipped code',()=>{
 const inert=['// Skip = disabled','/* Skip = disabled */','const x="Skip = disabled";','var x=@"Skip = disabled";','var x=$"Skip = {disabled}";','var x=$@"Skip = {disabled}";','var x="""Skip = disabled""";','var x=$$"""Skip = {{disabled}}""";'];
 for(const source of inert) assert.equal(sourcePrecheck(source),true,source);
 const dead='#if false\n[Fact] void X() {}\n#endif';
 const attribute='[Fact'+'(Skip'+'="disabled")] void X() {}';
 const jsSkip=['test','.','skip("case",()=>{});'].join('');
 for(const source of [dead,attribute,jsSkip]) assert.equal(sourcePrecheck(source),false,source);
});
test('QA scenarios require executed evidence; exceptions are validated',()=>{const id='QAS-WI-123-11';assert.equal(scenarioCheck([{...row(id)}],[])[0].ok,false);assert.equal(scenarioCheck([{...row(id)}],[],{compiled:true,discoveredIds:[id],results:[{scenarioId:id,status:'passed',executed:true}]})[0].ok,true);});
test('each board adapter builds the right request in dry-run and never sends without apply',async()=>{
 const cases=[
  ['jira',c=>jira(c),'WI-123',[['GET','/rest/api/3/issue/WI-123'],['POST','/rest/api/3/issue/WI-123/comment'],['POST','/rest/api/3/issue/WI-123/attachments'],['POST','/rest/api/3/issue/WI-123/transitions'],['POST','/rest/api/3/issue/WI-123/remotelink']]],
  ['azure',c=>azureBoards(c),'WI-123',[['GET','/_apis/wit/workitems/WI-123?'],['POST','/_apis/wit/workitems/WI-123/comments?format=markdown&api-version=7.1-preview.4'],['POST','/_apis/wit/attachments?fileName=report.png&api-version=7.1'],['PATCH','/_apis/wit/workitems/WI-123?api-version=7.1'],['PATCH','/_apis/wit/workitems/WI-123?api-version=7.1']]],
  ['linear',c=>linear(c),'WI-123',Array(5).fill(['POST','/graphql'])],
  ['github',c=>github({...c,repo:'acme/qa'}),'12',[['GET','/repos/acme/qa/issues/12'],['POST','/repos/acme/qa/issues/12/comments'],['POST','/repos/acme/qa/issues/12/comments'],['PATCH','/repos/acme/qa/issues/12'],['POST','/repos/acme/qa/issues/12/comments']]]
 ];
 for(const [name,make,id,expected] of cases){let calls=0;const a=make({baseUrl:'https://board.invalid',token:'never-real',dryRun:true,fetchImpl:()=>{calls++;throw Error('network')}});const artifact={filename:'report.png',contentType:'image/png',contentBase64:'aGVsbG8='};const operations=[()=>a.read(id),()=>a.comment(id,'note','key'),()=>name==='jira'||name==='azure'?a.attach(id,artifact):a.attach(id,'https://evidence.invalid/file'),()=>a.transition(id,'Done',3),()=>a.linkPr(id,'https://git.invalid/pr/1')];for(let i=0;i<operations.length;i++){const request=await operations[i]();assert.equal(request.dryRun,true,name);assert.equal(request.request.method,expected[i][0],`${name} op ${i}`);assert.ok(request.request.url.includes(expected[i][1]),`${name} op ${i}`);assert.doesNotMatch(JSON.stringify(request),/never-real/);}assert.equal(calls,0,name);}
});
test('all runner result parsers extract scenario ids and skip correctly',()=>{assert.equal(parseJunitXml('<testcase name="QAS-WI-123-12"><skipped/></testcase>')[0].scenario_id,'QAS-WI-123-12');assert.equal(parseJunitXml('<testcase name="QAS-WI-123-12"><skipped/></testcase>')[0].executed,false);assert.equal(parseTrx('<UnitTestResult testName="QAS-WI-123-13" outcome="Passed"/>')[0].scenario_id,'QAS-WI-123-13');assert.equal(parseAllureResults([{labels:[{name:'scenario_id',value:'QAS-WI-123-14'}],status:'passed'}])[0].scenario_id,'QAS-WI-123-14');assert.equal(parsePlaywrightJson({suites:[{specs:[{title:'case',tests:[{annotations:[{type:'scenario_id',description:'QAS-WI-123-15'}],results:[{status:'passed'}]}]}]}]})[0].scenario_id,'QAS-WI-123-15');});
import { html, reportMarker, reportRows, markdown } from '../lib/report.mjs';
test('HTML reports escape ticket-controlled content',()=>assert.equal(html([{id:'<script>x</script>',verdict:'FAILED',reason:'<img onerror=x>',screenshot:'a&b'}]).includes('<script>'),false));

test('authoritative install overlays branch copies from the QA source',()=>{const root=mkdtempSync(join(tmpdir(),'qa-authority-'));try{const src=join(root,'source'),dst=join(root,'app');mkdirSync(join(src,'tests'),{recursive:true});mkdirSync(join(dst,'tests'),{recursive:true});writeFileSync(join(src,'tests','case.txt'),'authority');writeFileSync(join(dst,'tests','case.txt'),'branch-copy');writeFileSync(join(src,'qa.config.json'),JSON.stringify({authoritativePaths:['tests']}));const cli=join(process.cwd(),'skillsets/test-automation/shared/ai-test-automation/templates/qa-kit/bin/qa.mjs');const r=spawnSync(process.execPath,[cli,'install-authoritative','--source',src,'--target',dst],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);assert.equal(readFileSync(join(dst,'tests','case.txt'),'utf8'),'authority');assert.match(r.stdout,/ignoredBranchCopies/);}finally{rmSync(root,{recursive:true,force:true});}});
test('board CLI is dry-run by default and redacts authorization',()=>{const cli=join(process.cwd(),'skillsets/test-automation/shared/ai-test-automation/templates/qa-kit/bin/qa.mjs');const config=join(process.cwd(),'skillsets/test-automation/shared/ai-test-automation/templates/qa-kit/qa.config.example.json');const r=spawnSync(process.execPath,[cli,'board','read','12','--config',config],{encoding:'utf8',env:{...process.env,QA_BOARD_WRITE_TOKEN:'test-secret-value'}});assert.equal(r.status,0,r.stderr);assert.match(r.stdout,/dry-run/);assert.doesNotMatch(r.stdout,/test-secret-value/);});

test('comment markers include item, commit and normalized content hash',()=>{const marker=reportMarker('WI-123','abcdef0','line\r\n two ');assert.match(marker,/WI-123:abcdef0:[a-f0-9]{16}/);assert.equal(marker,reportMarker('WI-123','abcdef0','line\n two'));});
test('each board dry-run includes a provider-specific body and revision guard',async()=>{const common={baseUrl:'https://board.invalid',repo:'acme/qa',token:'secret',dryRun:true};
 const j=await jira(common).comment('WI-123','report','<!-- qa-report:WI-123:abc:hash -->');assert.match(j.request.body,/qa-report:WI-123:abc:hash/);assert.equal(j.request.headers['x-atlassian-token'],'no-check');
 const a=await azureBoards(common).transition(123,'Done',7);assert.deepEqual(JSON.parse(a.request.body),[{op:'test',path:'/rev',value:7},{op:'add',path:'/fields/System.State',value:'Done'}]);
 const l=await linear(common).transition('issue-id','state-id','2026-01-01T00:00:00Z');assert.match(JSON.parse(l.request.body).query,/issueUpdate/);assert.equal(JSON.parse(l.request.body).variables.state,'state-id');
 const g=await github(common).transition(123,'closed');assert.deepEqual(JSON.parse(g.request.body),{state:'closed'});
 const ghMove=await github(common).moveProjectItem('project','item','field','option');assert.match(JSON.parse(ghMove.request.body).query,/updateProjectV2ItemFieldValue/);});
test('apply mode uses the injected fetch and returns its confirmed response',async()=>{let calls=0;const a=github({baseUrl:'https://api.github.com',repo:'acme/qa',token:'x',dryRun:false,fetchImpl:async(url,init)=>{calls++;assert.equal(url,'https://api.github.com/repos/acme/qa/issues/12?per_page=100');assert.equal(init.method,'GET');return {ok:true,status:200,headers:new Headers(),text:async()=>'{"updated_at":"now"}'}}});const result=await a.read(12);assert.equal(calls,1);assert.equal(result.data.updated_at,'now');});
test('every planned scenario remains in report, including related and regression scope',()=>{const rows=reportRows([{id:'QAS-WI-123-16',workItem:'WI-123',scope:'linked'},{id:'QAS-WI-100-01',workItem:'WI-100',scope:'regression'}],[{id:'QAS-WI-123-16',verdict:'VERIFIED',reason:'pass',executed:true},{id:'QAS-WI-100-01',verdict:'BLOCKED',reason:'removed from head'}],{posted:true});assert.equal(rows.length,2);assert.match(markdown(rows),/QAS-WI-100-01/);assert.equal(rows[1].reason,'removed from head');});
test('unposted report and missing screenshot fail closed',()=>{const rows=reportRows([{id:'QAS-WI-123-17',surface:'browser'},{id:'QAS-WI-123-17b'}],[{id:'QAS-WI-123-17',verdict:'VERIFIED',executed:true},{id:'QAS-WI-123-17b',verdict:'NOT_APPLICABLE',reason:'manual exception'}],{posted:false});assert.equal(rows[0].verdict,'BLOCKED');assert.match(rows[0].reason,/screenshot/);assert.equal(rows[1].verdict,'BLOCKED');assert.match(rows[1].reason,/report posting/);});
test('HTML report rejects javascript screenshot URLs and escapes all user fields',()=>{const out=html([{id:'<svg>',verdict:'BLOCKED',reason:'<script>',screenshot:'javascript:alert(1)'}]);assert.doesNotMatch(out,/<svg>|<script>|href="javascript:/);});
test('missing screenshot, attachment token, upload confirmation and failed attachment each block',()=>{const id='QAS-WI-123-18';assert.equal(judge([{...row(id),surface:'browser'}],[{scenario_id:id,status:'passed',executed:true}])[0].verdict,'BLOCKED');for(const evidence of [{missingToken:true},{uploadConfirmed:false},{attachmentFailed:true}])assert.equal(judge([row(id)],[{scenario_id:id,status:'passed',executed:true,...evidence}])[0].verdict,'BLOCKED');});
test('deleted base membership is derived from base even when head has no scenario',()=>{const base=['QAS-WI-100-02'];const verdict=judge([],[],base);assert.deepEqual(verdict.map(x=>[x.id,x.verdict,x.reason]),[['QAS-WI-100-02','BLOCKED','base scenario removed from head']]);});
test('all parsers distinguish skipped from executed results',()=>{assert.equal(parseJunitXml('<testcase name="QAS-WI-123-19"><skipped/></testcase>')[0].executed,false);assert.equal(parseTrx('<UnitTestResult testName="QAS-WI-123-20" outcome="NotExecuted"/>')[0].executed,false);assert.equal(parsePlaywrightJson({suites:[{specs:[{title:'QAS-WI-123-21',tests:[{annotations:[{type:'scenario_id',description:'QAS-WI-123-21'}],results:[{status:'skipped'}]}]}]}]})[0].executed,false);assert.equal(parseAllureResults([{labels:[{name:'scenario_id',value:'QAS-WI-123-22'}],status:'skipped'}])[0].executed,false);});

test('spoof guard strips line and block comments',()=>{const attribute='[Fact'+'(Skip'+'="x")]';assert.equal(sourcePrecheck(`// Skip = true\n/* ${attribute} */\n[Fact] void Real() {}`),true);});
test('spoof guard strips ordinary string literals',()=>{assert.equal(sourcePrecheck('const note = "Skip = true"; test("case", run);'),true);});
test('spoof guard strips C# verbatim and interpolated string literals',()=>{assert.equal(sourcePrecheck('var a = @"Skip = true"; var b = $@"quote: "" Skip = {flag}"; var c = @$"quote: "" still text";'),true);});
test('spoof guard strips raw and interpolated raw literals',()=>{assert.equal(sourcePrecheck('var a = """Skip = true"""; var b = $$"""Skip = {{flag}}""";'),true);});
test('spoof guard rejects a false preprocessor branch',()=>{assert.equal(sourcePrecheck('#if false\n[Fact] void Hidden() {}\n#endif'),false);});
test('spoof guard rejects a skipped attribute',()=>{const attribute='[Fact'+'(Skip'+'="reason")] void Hidden() {}';assert.equal(sourcePrecheck(attribute),false);});
test('spoof guard rejects skipped JavaScript test declarations',()=>{assert.equal(sourcePrecheck(['test','.','skip("case",()=>{});'].join('')),false);});
const hidden=(...parts)=>parts.join('');
for(const [name,code] of [
 ['fixme',hidden('test','.','fixme("case",async()=>{});')],
 ['fail-marked',hidden('test','.','fail("case",async()=>{});')],
 ['conditional fail',hidden('test','.','fail(browserName==="webkit");')],
 ['focused',hidden('test','.','only("case",async()=>{});')],
 ['focused describe',hidden('test','.describe.','only("group",()=>{});')],
 ['slowed',hidden('test','.','slow();')],
 ['timeout-extended',hidden('test','.set','Timeout(120000);')],
 ['fixed sleep',hidden('await page.wait','ForTimeout(5000);')],
 ['suite-level timeout',hidden('test.describe.','configure({ time','out: 120000 });')],
 ['suite-level timeout with mode',hidden('test.describe.','configure({ mode: "serial",\n time','out: 0 });')],
 ['suite-level retries',hidden('test.describe.','configure({ mode: "serial", ret','ries: 3 });')],
 ['use actionTimeout',hidden('test.','use({ action','Timeout: 60000 });')],
 ['use navigationTimeout',hidden('test.','use({ navigation','Timeout: 60000 });')],
 ['retried',hidden('test.describe.configure({ ret','ries: 2 });')],
 ['pytest skip',hidden('@pytest.mark.','skip(reason="later")\ndef test_x(): pass')],
 ['pytest xfail',hidden('@pytest.mark.','xfail\ndef test_x(): pass')],
]) test(`spoof guard rejects a ${name} test`,()=>{assert.equal(sourcePrecheck(code),false);});
for(const [name,code] of [
 ['pytest skipif',hidden('@pytest.mark.','skipif(sys.platform == "win32", reason="x")\ndef test_x(): pass')],
 ['pytest skip call',hidden('def test_x():\n    pytest.','skip("later")')],
 ['pytest importorskip',hidden('np = pytest.','importorskip("numpy")')],
 ['pytest xfail call',hidden('def test_x():\n    pytest.','xfail("known")')],
 ['pytest xfail strict marker',hidden('@pytest.mark.','xfail(strict=True)\ndef test_x(): pass')],
 ['unittest skip',hidden('@unittest.','skip("later")\ndef test_x(self): pass')],
 ['unittest skipIf',hidden('@unittest.','skipIf(sys.platform == "win32", "x")\ndef test_x(self): pass')],
 ['unittest skipUnless',hidden('@unittest.','skipUnless(HAS_DB, "x")\ndef test_x(self): pass')],
 ['unittest expectedFailure',hidden('@unittest.','expectedFailure\ndef test_x(self): pass')],
 ['unittest skipTest call',hidden('def test_x(self):\n    self.','skipTest("later")')],
 ['imported skipIf decorator',hidden('from unittest import ','skipIf\n@skipIf(True, "x")\ndef test_x(self): pass')],
 ['playwright conditional skip in body',hidden('test("c", async ({ page, browserName }) => {\n  test.','skip(browserName === "webkit", "flaky");\n});')],
 ['playwright conditional fixme in body',hidden('test("c", async ({ browserName }) => {\n  test.','fixme(browserName === "firefox", "broken");\n});')],
 ['describe skip',hidden('describe.','skip("group", () => {});')],
 ['it skip',hidden('it.','skip("case", () => {});')],
 ['it skip each',hidden('it.skip','.each([1, 2])("case %i", () => {});')],
 ['test.describe skip',hidden('test.describe.','skip("group", () => {});')],
 ['xit',hidden('x','it("case", () => {});')],
 ['xtest',hidden('x','test("case", () => {});')],
 ['xdescribe',hidden('x','describe("group", () => {});')],
 ['vitest todo',hidden('test.','todo("later");')],
 ['vitest skipIf',hidden('test.','skipIf(process.env.CI)("case", () => {});')],
 ['vitest runIf',hidden('test.','runIf(process.env.RUN_IT)("case", () => {});')],
 ['vitest concurrent skip',hidden('it.concurrent.','skip("case", () => {});')],
 ['NUnit Ignore attribute',hidden('[','Ignore("later")]\npublic void Hidden() {}')],
 ['NUnit Assert.Ignore',hidden('Assert.','Ignore("later");')],
 ['MSTest Assert.Inconclusive',hidden('Assert.','Inconclusive("later");')],
 ['xunit Skip.If',hidden('Skip.','If(Environment.GetEnvironmentVariable("CI") != null);')],
]) test(`spoof guard rejects a conditional or alternate skip: ${name}`,()=>{assert.equal(sourcePrecheck(code),false);});
for(const [name,code] of [
 ['imported expectedFailure decorator',hidden('@expected','Failure\ndef test_x(self): pass')],
 ['imported skipUnless decorator',hidden('@skip','Unless(HAS_DB, "x")\ndef test_x(self): pass')],
 ['imported bare skip decorator',hidden('@sk','ip("later")\ndef test_x(self): pass')],
 ['module-qualified skipIf decorator',hidden('@helpers.skip','If(CI, "x")\ndef test_x(self): pass')],
 ['skipTest on another test object',hidden('def test_x(case):\n    case.skip','Test("later")')],
]) test(`spoof guard still rejects a real skip: ${name}`,()=>{assert.equal(sourcePrecheck(code),false);});
for(const [name,code] of [
 ['python helper named expectedFailure','def expectedFailure(value):\n    return value\n'],
 ['python helper named skipIf','def skipIf(condition, reason):\n    return condition\n'],
 ['python assignment to skipTest','skipTest = 3\nexpectedFailure = lambda f: f\n'],
 ['python plain references','handlers = [skipUnless, expectedFailure]\nvalue = config.skipIf\nprint(opts.expectedFailure, skipTest)\n'],
 ['js function named skipIf','function skipIf(condition) { return condition; }\n'],
 ['js const assignment to expectedFailure','const expectedFailure = (value) => value;\nlet skipUnless = 1;\n'],
 ['js plain references and property reads','const handlers = [skipIf, skipTest];\nconst value = config.skipUnless + options.expectedFailure;\n'],
]) test(`spoof guard accepts ${name}`,()=>{assert.equal(sourcePrecheck(code),true);});
test('spoof guard ignores every new skip form inside comments and strings',()=>{assert.equal(sourcePrecheck(hidden('// @pytest.mark.','skipif(x)\n# unittest.','skipIf(x)\n/* x','it("a") test.','skipIf(c) test.','todo("t") */\nconst a = "pytest.','importorskip(x) @unittest.','expectedFailure test.','skip(c, \'r\') [','Ignore] Assert.','Inconclusive";\nawait expect(a).toHaveText("b");')),true);});
test('spoof guard accepts identifiers that merely contain skip, todo or only',()=>{assert.equal(sourcePrecheck('const skipped = rows.filter(r => r.skipIfEmpty);\nconst todos = list.todoCount + only.length;\nawait expect(page.getByRole("heading")).toHaveText("Done",{useInnerText:true});'),true);});
test('spoof guard ignores hidden-red words inside comments and strings',()=>{assert.equal(sourcePrecheck(hidden('// test','.fixme(x)\nconst note = "test','.fail( and retries: 3";\nawait expect(a).toHaveText("b");')),true);});
test('spoof guard accepts describe.configure without timeout or retries and use without timeouts',()=>{assert.equal(sourcePrecheck('test.describe.configure({ mode: "serial" });\ntest.use({ viewport: { width: 800, height: 600 } });'),true);});
test('spoof guard keeps accepting a plain strict test',()=>{assert.equal(sourcePrecheck('test("case",async({page})=>{await expect(page.getByRole("heading")).toHaveText("Done",{useInnerText:true});});'),true);});
test('manual exception requires reason owner and procedure in storage and judge',()=>{const s={...row('QAS-WI-123-23','manual'),reason:'needs visual review',owner:'qa',procedure:'open page and inspect'};assert.equal(validateStoreAndGate(s).valid,true);});
test('manual exception missing procedure is blocked in both paths',()=>{const s={...row('QAS-WI-123-24','manual'),reason:'needs review',owner:'qa'};assert.deepEqual(validateStoreAndGate(s),{valid:false,verdict:'BLOCKED'});});
test('awaiting exception requires owner reason and revisit date in both paths',()=>{const s={...row('QAS-WI-123-25','awaiting'),reason:'sandbox unavailable',owner:'qa',revisitDate:'2027-01-01'};assert.equal(validateStoreAndGate(s).valid,true);});
test('awaiting exception without revisit date blocks in both paths',()=>{const s={...row('QAS-WI-123-26','awaiting'),reason:'sandbox unavailable',owner:'qa'};assert.deepEqual(validateStoreAndGate(s),{valid:false,verdict:'BLOCKED'});});
test('skipped test is not executed evidence',()=>{assert.equal(judge([row('QAS-WI-123-27')],[{scenario_id:'QAS-WI-123-27',status:'skipped',executed:false}])[0].verdict,'BLOCKED');});
test('missing browser screenshot blocks only executed browser scenario',()=>{assert.equal(judge([{...row('QAS-WI-123-28'),surface:'browser'}],[{scenario_id:'QAS-WI-123-28',status:'passed',executed:true}])[0].reason,'missing screenshot');});
test('failed attachment blocks an otherwise passing scenario',()=>{assert.equal(judge([row('QAS-WI-123-29')],[{scenario_id:'QAS-WI-123-29',status:'passed',executed:true,attachmentFailed:true}])[0].verdict,'BLOCKED');});
test('missing upload token blocks an otherwise passing scenario',()=>{assert.equal(judge([row('QAS-WI-123-30')],[{scenario_id:'QAS-WI-123-30',status:'passed',executed:true,missingToken:true}])[0].verdict,'BLOCKED');});
test('unconfirmed attachment upload blocks an otherwise passing scenario',()=>{assert.equal(judge([row('QAS-WI-123-31')],[{scenario_id:'QAS-WI-123-31',status:'passed',executed:true,uploadConfirmed:false}])[0].verdict,'BLOCKED');});
test('changed content under an existing scenario id counts as in-change',()=>{const positive=row('QAS-WI-123-32');const negative=row('QAS-WI-123-32n','automated','api',{polarity:'negative'});const regression=row('QAS-WI-123-32r','automated','api',{regressionCase:true});const before=positive;const after={...positive,expected:'new'};assert.equal(scenarioCheck([after,negative,regression],[positive,negative,regression],{compiled:true,discoveredIds:[after.id],results:[{scenarioId:after.id,status:'passed',executed:true}]}).find(x=>x.id===after.id).changed,true);});
test('repeated CLI options preserve every supplied value',()=>{assert.deepEqual(parseArgs(['--item','WI-1','--item','WI-2','--source','a.cs','--source','b.cs']).item,['WI-1','WI-2']);assert.deepEqual(parseArgs(['--source','a.cs','--source','b.cs']).source,['a.cs','b.cs']);});
test('JUnit XML parser extracts stable scenario id',()=>{assert.equal(parseJunitXml('<testcase name="checkout QAS-WI-123-33"/>')[0].scenario_id,'QAS-WI-123-33');});
test('TRX parser extracts stable scenario id',()=>{assert.equal(parseTrx('<UnitTestResult testName="checkout QAS-WI-123-34" outcome="Passed"/>')[0].scenario_id,'QAS-WI-123-34');});
test('Playwright JSON parser extracts annotation scenario id',()=>{assert.equal(parsePlaywrightJson({suites:[{specs:[{title:'case',tests:[{annotations:[{type:'scenario_id',description:'QAS-WI-123-35'}],results:[{status:'passed'}]}]}]}]})[0].scenario_id,'QAS-WI-123-35');});
test('Allure results parser extracts custom scenario_id label',()=>{assert.equal(parseAllureResults([{labels:[{name:'scenario_id',value:'QAS-WI-123-36'}],status:'passed'}])[0].scenario_id,'QAS-WI-123-36');});
test('Jira adapter request stays dry-run and includes comment body',async()=>{const req=await jira({baseUrl:'https://acme.atlassian.net',dryRun:true}).comment('WI-123','text','<!-- qa-report:WI-123:sha:hash -->');assert.equal(req.request.method,'POST');assert.match(req.request.url,/rest\/api\/3\/issue\/WI-123\/comment$/);assert.match(req.request.body,/qa-report:WI-123:sha:hash/);});
test('Azure adapter request stays dry-run and includes revision test op',async()=>{const req=await azureBoards({baseUrl:'https://dev.azure.com/acme',dryRun:true}).transition(123,'Done',9);assert.equal(req.request.method,'PATCH');assert.deepEqual(JSON.parse(req.request.body)[0],{op:'test',path:'/rev',value:9});});
test('Linear adapter request stays dry-run and preserves GraphQL variables',async()=>{const req=await linear({dryRun:true}).comment('issue-id','text','marker');assert.equal(req.request.method,'POST');assert.equal(JSON.parse(req.request.body).variables.id,'issue-id');assert.match(JSON.parse(req.request.body).variables.body,/marker/);});
test('GitHub adapter request stays dry-run and preserves issue comment marker',async()=>{const req=await github({baseUrl:'https://api.github.com',repo:'acme/qa',dryRun:true}).comment(123,'text','<!-- qa-report:WI-123:sha:hash -->');assert.equal(req.request.method,'POST');assert.match(JSON.parse(req.request.body).body,/qa-report:WI-123:sha:hash/);});

function validateStoreAndGate(scenario){const store=scenarioCheck([scenario],[])[0];const gate=judge([scenario],[])[0];return {valid:store.ok,verdict:gate.verdict};}

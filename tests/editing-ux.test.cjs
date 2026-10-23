const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
const root='/api/production/projects/p/storyboards/b/editing';
async function fixture(t, overrides={}) {
  assert.ok(fs.existsSync('app/static/editing.html'),'standalone editing page exists');
  const browser=await chromium.launch({headless:true,...(process.env.FRAMEPILOT_CHROME?{executablePath:process.env.FRAMEPILOT_CHROME}:{})});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:390,height:844}});
  page.on('dialog',dialog=>dialog.accept());
  const state={timeline:null,versions:[],exports:[],audio:[],selected_clips:[{run_id:'a',shot_key:'镜头一',duration_ms:4000,media_url:'/a.mp4'},{run_id:'b',shot_key:'镜头二',duration_ms:3000,media_url:'/b.mp4'}],source_version:2,source_current:true,confirmed:true,...overrides};
  const calls=[];let conflict=false, loseExport=false, exportConflict=false;
  await page.route('**/*',async route=>{
    const req=route.request(), url=new URL(req.url());
    if(url.pathname.startsWith(root)) {
      const body=req.postData()?JSON.parse(req.postData()):null;calls.push({path:url.pathname,method:req.method(),body});
      if(req.method()==='GET') return route.fulfill({json:url.pathname.endsWith('/timeline')?state.versions.find(x=>x.version===Number(url.searchParams.get('version'))):state});
      if(url.pathname.endsWith('/timeline')){
        if(conflict)return route.fulfill({status:409,json:{detail:'版本已改变'}});
        state.timeline={version:(state.timeline?.version||0)+1,source_version:body.source_version,content:body.content,applicable:true};state.versions.push(state.timeline);return route.fulfill({json:state.timeline});
      }
      if(url.pathname.endsWith('/exports')){
        if(exportConflict)return route.fulfill({status:409,json:{detail:'来源变化'}});
        if(loseExport){loseExport=false;return route.abort();}
        state.exports=[{id:'e',status:'queued',timeline_version:body.expected_version}];return route.fulfill({json:state.exports[0]});
      }
      if(url.pathname.endsWith('/accept')){state.exports[0].acceptance={comment:body.comment};return route.fulfill({json:state.exports[0]});}
      return route.fulfill({json:{}});
    }
    if(url.pathname==='/editing')return route.fulfill({contentType:'text/html',body:fs.readFileSync('app/static/editing.html','utf8')});
    if(url.pathname.startsWith('/static/'))return route.fulfill({contentType:url.pathname.endsWith('.js')?'text/javascript':'text/css',body:fs.readFileSync('app'+url.pathname,'utf8')});
    return route.fulfill({body:''});
  });
  await page.goto('http://localhost/editing?project=p&board=b');
  await page.locator('#clips .clip').first().waitFor();
  return {page,state,calls,setConflict:()=>conflict=true,setLoseExport:()=>loseExport=true,setExportConflict:()=>exportConflict=true};
}

test('选片顺序、原声默认值、裁切字幕音轨及不可变保存',async t=>{
  const {page,calls,state}=await fixture(t);
  assert.equal(await page.locator('#clips .clip').count(),2);
  assert.equal(await page.locator('[data-field=gain]').first().inputValue(),'1');
  assert.equal(await page.locator('#export').isDisabled(),true,'未保存不导出');
  await page.getByRole('button',{name:'镜头二 上移'}).click();
  await page.locator('[data-field=start_ms]').first().fill('0.5');
  await page.getByRole('button',{name:'添加字幕',exact:true}).click();
  await page.locator('#subtitles [data-field=text]').fill('字幕 <img src=x>');
  await page.locator('#subtitles [data-field=end_ms]').fill('2');
  await page.locator('#preset').selectOption('portrait');
  await page.locator('#save').click();
  await page.waitForFunction(()=>document.querySelector('#export').disabled===false);
  assert.deepEqual(state.timeline.content.clips,[{run_id:'b',start_ms:500,end_ms:3000,gain:1},{run_id:'a',start_ms:0,end_ms:4000,gain:1}]);
  assert.equal(state.timeline.content.preset,'portrait');assert.equal(state.timeline.content.subtitles[0].text,'字幕 <img src=x>');
  assert.equal(calls.find(x=>x.path.endsWith('/timeline')&&x.body).body.source_version,2);
  await page.locator('#export').click();
  await page.waitForFunction(()=>document.querySelector('#exports').textContent.includes('排队'));
  assert.match(await page.locator('#exports').textContent(),/独立渲染进程/);
  assert.equal(await page.locator('#exports video').count(),0);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'390px无横向溢出');
  if(process.env.FRAMEPILOT_EDITING_SCREENSHOT)await page.screenshot({path:process.env.FRAMEPILOT_EDITING_SCREENSHOT,fullPage:true});
});

test('过期来源、版本冲突和渲染成功后人工验收分离',async t=>{
  const {page,state,setConflict,calls}=await fixture(t);
  setConflict();await page.locator('#save').click();await page.locator('#error').waitFor();
  assert.match(await page.locator('#error').textContent(),/版本|重新读取/);
  assert.equal(await page.locator('#export').isDisabled(),true);
  state.source_current=false;await page.locator('#refresh').click();
  assert.equal(await page.locator('#save').isDisabled(),true);
  state.source_current=true;state.timeline={version:1,source_version:2,applicable:true,content:{preset:'landscape',clips:[{run_id:'a',start_ms:0,end_ms:4000,gain:1}],subtitles:[],audio_tracks:[]}};
  state.exports=[{id:'e',status:'succeeded',timeline_version:1,media_url:root+'/exports/e/media'}];
  await page.locator('#refresh').click();await page.locator('#exports video').waitFor();
  assert.equal(await page.locator('#exports video').getAttribute('controls'),'');
  assert.match(await page.locator('#exports').textContent(),/未人工验收/);
  await page.getByLabel('成片验收意见').fill('已人工检查声音和字幕');
  await page.getByRole('button',{name:'记录人工验收'}).click();
  await page.waitForFunction(()=>document.querySelector('#exports').textContent.includes('已人工验收'));
  assert.equal(calls.at(-2)?.body?.comment||calls.find(x=>x.path.endsWith('/accept')).body.comment,'已人工检查声音和字幕');
});

test('导出响应丢失后刷新仍用原幂等请求恢复',async t=>{
  const {page,calls,setLoseExport}=await fixture(t);
  await page.locator('#save').click();await page.waitForFunction(()=>!document.querySelector('#export').disabled);
  setLoseExport();await page.locator('#export').click();await page.locator('#retry-export').waitFor();
  const original=calls.find(x=>x.path.endsWith('/exports')&&x.body).body;
  await page.reload();await page.locator('#retry-export').waitFor();await page.locator('#retry-export').click();
  await page.waitForFunction(()=>document.querySelector('#exports').textContent.includes('排队'));
  assert.deepEqual(calls.filter(x=>x.path.endsWith('/exports')&&x.body).at(-1).body,original);
});


test('音轨配置与历史只读，非法裁切不会发送保存请求',async t=>{
  const {page,state,calls}=await fixture(t,{audio:[{id:'music',filename:'配乐.wav'}]});
  await page.getByRole('button',{name:'添加音轨',exact:true}).click();
  await page.locator('#audio-tracks [data-field=offset_ms]').fill('1.5');
  await page.locator('#audio-tracks [data-field=gain]').fill('0.4');
  await page.getByLabel('循环至片尾').check();
  await page.locator('#clips [data-field=end_ms]').first().fill('0.1');
  await page.locator('#save').click();await page.locator('#error').waitFor();
  assert.match(await page.locator('#error').textContent(),/0.2 秒/);
  assert.equal(calls.filter(x=>x.method==='POST').length,0);
  await page.locator('#clips [data-field=end_ms]').first().fill('4');
  await page.locator('#save').click();await page.waitForFunction(()=>!document.querySelector('#export').disabled);
  assert.deepEqual(state.timeline.content.audio_tracks,[{asset_id:'music',offset_ms:1500,gain:0.4,loop:true}]);
  await page.locator('#history').selectOption('1');
  await page.waitForFunction(()=>document.querySelector('#save-state').textContent.includes('只读'));
  assert.equal(await page.locator('#clips input').first().isDisabled(),true);
  assert.equal(await page.locator('#export').isDisabled(),true);
  await page.locator('#history').selectOption('latest');
  await page.waitForFunction(()=>!document.querySelector('#clips input').disabled);
  await page.locator('#preset').selectOption('square');
  assert.equal(await page.locator('#export').isDisabled(),true);
});

test('渲染失败和未知任务只显示真实状态，缺失参数不发送请求',async t=>{
  const {page,calls}=await fixture(t,{exports:[{id:'broken',version:1,status:'failed',error:'素材解码失败 <img src=x>'},{id:'interrupted',version:1,status:'unknown'}]});
  assert.match(await page.locator('#exports').textContent(),/渲染失败/);
  assert.match(await page.locator('#exports').textContent(),/不会自动重新渲染/);
  assert.equal(await page.locator('#exports img,#exports video').count(),0);
  assert.equal(calls.filter(x=>x.method==='POST').length,0);
  await page.goto('http://localhost/editing');await page.locator('#error').waitFor();
  assert.match(await page.locator('#error').textContent(),/project 和 board/);
  assert.equal(await page.locator('#add-subtitle').isDisabled(),true);
  assert.equal(await page.locator('#save').isDisabled(),true);
  assert.equal(calls.filter(x=>x.method==='POST').length,0);
});

test('导出明确被服务端拒绝后不留下无法恢复的待确认请求',async t=>{
  const {page,setExportConflict}=await fixture(t);
  await page.locator('#save').click();await page.waitForFunction(()=>!document.querySelector('#export').disabled);
  setExportConflict();await page.locator('#export').click();await page.locator('#error').waitFor();
  assert.equal(await page.locator('#pending-panel').isHidden(),true);
  assert.equal(await page.evaluate(()=>localStorage.getItem('framepilot:editing:export:p:b')),null);
  await page.locator('#refresh').click();await page.waitForFunction(()=>!document.querySelector('#export').disabled);
});


test('其他标签更新后刷新验收记录不会导出未显示的新时间线',async t=>{
  const initial={version:1,source_version:2,applicable:true,content:{preset:'landscape',clips:[{run_id:'a',start_ms:0,end_ms:4000,gain:1}],subtitles:[],audio_tracks:[]}};
  const {page,state,calls}=await fixture(t,{timeline:initial,versions:[initial],exports:[{id:'e',status:'succeeded',version:1}]});
  assert.equal(await page.locator('#export').isDisabled(),false);
  state.timeline={...initial,version:2,content:{...initial.content,preset:'portrait'}};
  state.versions.push(state.timeline);
  await page.getByRole('button',{name:'记录人工验收'}).click();
  await page.waitForFunction(()=>document.querySelector('#exports').textContent.includes('已人工验收'));
  assert.equal(await page.locator('#preset').inputValue(),'landscape','保留当前显示的旧内容');
  assert.equal(await page.locator('#export').isDisabled(),true,'需明确重新读取新版本');
  assert.equal(calls.filter(x=>x.path.endsWith('/exports')&&x.method==='POST').length,0);
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>document.querySelector('#preset').value==='portrait');
  assert.equal(await page.locator('#export').isDisabled(),false);
});

const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');

async function fixture(t,{project='p',width=1440,proposals=[],lose=false,replyStatus='succeeded'}={}) {
  const browser=await chromium.launch({headless:true,...(process.env.FRAMEPILOT_CHROME?{executablePath:process.env.FRAMEPILOT_CHROME}:{})});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width,height:900}}), calls=[];
  page.on('pageerror',error=>console.error('Browser error:',error.message));
  const threads=new Map(); let dropped=lose;
  const summary=id=>threads.get(id);
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url()),body=req.postData()?JSON.parse(req.postData()):null;
    if(url.pathname==='/api/production/model-profiles')return route.fulfill({json:[{id:'m',version:2,executable:true,config:{name:'文本模型',model:'configured-model',adapter:'openai_chat',purpose:'text'},reasoning_options:['default','high']}]});
    if(url.pathname.startsWith('/api/assistant/')) {
      calls.push({path:url.pathname,method:req.method(),body});
      if(url.pathname==='/api/assistant/threads') {
        const id=body.project_id?'thread-'+body.project_id:'thread-free';
        if(!threads.has(id))threads.set(id,{id,project_id:body.project_id||null,revision:0,messages:[],proposals:structuredClone(proposals),active:false});
        return route.fulfill({json:summary(id)});
      }
      const parts=url.pathname.split('/'),thread=summary(parts[4]);
      if(!thread)return route.fulfill({status:404,json:{detail:'找不到会话'}});
      if(req.method()==='GET')return route.fulfill({json:thread});
      if(parts.at(-1)==='messages') {
        if(!thread.messages.some(x=>x.text===body.text)){
          thread.revision++;thread.messages.push({id:'u1',role:'user',text:body.text},{id:'a1',role:'assistant',text:'已读取 <img src=x onerror=alert(1)>',status:replyStatus});
        }
        if(dropped){dropped=false;return route.abort();}
        return route.fulfill({json:thread});
      }
      if(parts.at(-1)==='decision') {
        const proposal=thread.proposals.find(x=>x.id===parts[6]);
        proposal.status=body.decision==='reject'?'rejected':'accepted';if(proposal.kind==='writer_create'&&body.decision==='accept')thread.project_id='created-project';proposal.result={stage:'writer',project_id:thread.project_id,result:{updated:true}};thread.revision++;
        return route.fulfill({json:thread});
      }
      if(parts.at(-1)==='abandon'&&parts[5]==='proposals') {thread.proposals.find(x=>x.id===parts[6]).status='unknown';thread.active=false;return route.fulfill({json:thread});}
      return route.fulfill({json:thread});
    }
    if(url.pathname.startsWith('/static/'))return route.fulfill({contentType:url.pathname.endsWith('.js')?'text/javascript':'text/css',body:fs.existsSync('app'+url.pathname)?fs.readFileSync('app'+url.pathname,'utf8'):''});
    return route.fulfill({contentType:'text/html',body:`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><link rel="stylesheet" href="/static/studio-ui.css"></head><body><header>旧页头</header><main id="old-workspace"><input id="existing-input" value="保留编辑"><div style="height:1800px">工作区</div></main><script src="/static/studio-ui.js"></script><script>window.ctx={project_id:${JSON.stringify(project)},storyboard_id:'b',workspace_dirty:false};window.results=[];window.studio=FramePilotStudio.mount({stage:'writer',workspace:document.querySelector('main'),getContext:()=>ctx,onResult:r=>{results.push(r);if(!ctx.project_id)ctx.project_id=r.project_id;}});</script></body></html>`});
  });
  await page.goto('http://localhost/?project='+project);
  assert.equal(await page.evaluate(()=>typeof window.FramePilotStudio),'object','shared assistant mount API exists');
  await page.waitForFunction(()=>document.querySelector('#assistant-status')?.textContent==='已连接',{},{timeout:5000}).catch(async error=>{throw new Error(error.message+' '+await page.locator('body').innerText());});
  return {page,calls,threads};
}

test('共享分栏保留工作区，导航携带上下文，键盘调整和收起恢复',async t=>{
  const {page}=await fixture(t);
  if(process.env.FRAMEPILOT_STUDIO_CAPTURE){fs.mkdirSync('.impeccable/review',{recursive:true});await page.screenshot({path:'.impeccable/review/studio-shared-desktop.png',fullPage:true});}
  assert.equal(await page.locator('#existing-input').inputValue(),'保留编辑');
  assert.equal(Math.round((await page.locator('#assistant-panel').boundingBox()).width),360);
  assert.match(await page.locator('#studio-nav a[href*="storyboard"]').getAttribute('href'),/project=p.*board=b.*thread=thread-p/);
  await page.locator('#studio-separator').focus();await page.keyboard.press('ArrowRight');
  assert.equal(Math.round((await page.locator('#assistant-panel').boundingBox()).width),380);
  await page.getByRole('button',{name:'收起助手'}).click();assert.equal(await page.locator('#assistant-panel').isVisible(),false);
  await page.getByRole('button',{name:'展开助手'}).click();assert.equal(await page.locator('#assistant-panel').isVisible(),true);
});

test('发送固定模型版本与上下文，中文输入法不会误发，模型文本安全显示',async t=>{
  const {page,calls}=await fixture(t);
  await page.locator('#assistant-input').fill('帮我检查');
  await page.locator('#assistant-effort').selectOption('high');
  await page.locator('#assistant-input').dispatchEvent('keydown',{key:'Enter',isComposing:true});
  assert.equal(calls.filter(x=>x.path.endsWith('/messages')).length,0);
  await page.locator('#assistant-input').press('Enter');
  await page.waitForFunction(()=>document.querySelector('#assistant-messages').textContent.includes('已读取'));
  const sent=calls.find(x=>x.path.endsWith('/messages')).body;
  assert.deepEqual(sent.profile,{profile_id:'m',version:2});assert.equal(sent.context.stage,'writer');assert.equal(sent.reasoning_effort,'high');
  assert.equal(await page.locator('#assistant-messages img').count(),0);
});

test('未知请求显式重试沿用原始幂等键，刷新仅 GET，跨项目不复用会话',async t=>{
  const {page,calls}=await fixture(t,{lose:true});
  await page.locator('#assistant-input').fill('原始请求');await page.getByRole('button',{name:'发送消息',exact:true}).click();
  await page.getByRole('button',{name:'重试原请求',exact:true}).waitFor();
  const original=calls.find(x=>x.path.endsWith('/messages')).body;
  await page.getByRole('button',{name:'刷新会话',exact:true}).click();
  assert.equal(calls.filter(x=>x.path.endsWith('/messages')).length,1);
  await page.getByRole('button',{name:'重试原请求',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('#assistant-retry'));
  assert.deepEqual(calls.filter(x=>x.path.endsWith('/messages'))[1].body,original);
  await page.locator('#assistant-input').fill('保留草稿');
  await page.evaluate(()=>{ctx.project_id='other';studio.setContext(ctx);});
  await page.waitForFunction(()=>document.querySelector('#studio-root').dataset.thread==='thread-other');
  assert.equal(await page.locator('#assistant-input').inputValue(),'保留草稿');
  assert.equal(await page.locator('#assistant-messages').textContent().then(x=>x.includes('原始请求')),false);
});

test('未保存时拒绝仍可执行，接受受阻，成功只通知工作区一次',async t=>{
  const p={id:'proposal',kind:'writer',title:'修改草稿',summary:'修改建议',status:'pending',available:true,preview:{before:'旧文',after:'新文'}};
  const {page,calls}=await fixture(t,{proposals:[p]});
  await page.evaluate(()=>{ctx.workspace_dirty=true;studio.setContext(ctx);});
  assert.equal(await page.getByRole('button',{name:'接受并执行',exact:true}).isDisabled(),true);
  assert.equal(await page.getByRole('button',{name:'拒绝',exact:true}).isEnabled(),true);
  await page.evaluate(()=>{ctx.workspace_dirty=false;studio.setContext(ctx);});
  await page.getByRole('button',{name:'接受并执行',exact:true}).click();
  await page.waitForFunction(()=>results.length===1);
  await page.getByRole('button',{name:'刷新会话',exact:true}).click();
  assert.equal(await page.evaluate(()=>results.length),1);
  assert.equal(calls.find(x=>x.path.endsWith('/decision')).body.workspace_dirty,false);
});

test('移动端保留两个面板 DOM 和编辑状态，无横向溢出',async t=>{
  const {page}=await fixture(t,{width:390});
  await page.locator('#assistant-input').fill('尚未发送');
  if(process.env.FRAMEPILOT_STUDIO_CAPTURE){fs.mkdirSync('.impeccable/review',{recursive:true});await page.screenshot({path:'.impeccable/review/studio-shared-mobile.png',fullPage:true});}
  await page.getByRole('button',{name:'工作区',exact:true}).click();
  assert.equal(await page.locator('#studio-workspace').isVisible(),true);
  await page.locator('#existing-input').fill('还在编辑');
  await page.getByRole('button',{name:'助手',exact:true}).click();
  assert.equal(await page.locator('#assistant-input').inputValue(),'尚未发送');
  assert.equal(await page.locator('#existing-input').inputValue(),'还在编辑');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
});

test('重载保留未知请求，显式重试使用原固定模型与键；未绑定会话连续导航',async t=>{
  const {page,calls}=await fixture(t,{project:null,lose:true});
  await page.locator('#assistant-input').fill('未绑定消息');await page.getByRole('button',{name:'发送消息',exact:true}).click();
  await page.getByRole('button',{name:'重试原请求',exact:true}).waitFor();
  const original=calls.find(x=>x.path.endsWith('/messages')).body;
  await page.reload();await page.getByRole('button',{name:'重试原请求',exact:true}).waitFor();
  assert.equal(calls.filter(x=>x.path.endsWith('/messages')).length,1);
  await page.getByRole('button',{name:'重试原请求',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('#assistant-retry'));
  assert.deepEqual(calls.filter(x=>x.path.endsWith('/messages'))[1].body,original);
  await page.locator('#assistant-input').fill('跨页草稿');
  const target=await page.locator('#studio-nav a[data-stage=storyboard]').getAttribute('href');
  assert.match(target,/thread=thread-free/);await page.goto('http://localhost'+target);
  await page.waitForFunction(()=>document.querySelector('#assistant-status').textContent==='已连接');
  assert.equal(calls.filter(x=>x.path==='/api/assistant/threads').length,1,'navigation does not create another unbound thread');
  assert.equal(calls.filter(x=>x.path.endsWith('/messages')).length,2,'navigation never calls the model');
  assert.equal(await page.locator('#assistant-input').inputValue(),'跨页草稿');
});

test('拒绝建议只提交拒绝决定，历史成功不重新通知，拖拽限制宽度',async t=>{
  const proposals=[{id:'past',title:'已完成建议',status:'succeeded',result:{project_id:'p',stage:'writer'}},{id:'new',title:'待处理建议',status:'pending',available:true}];
  const {page,calls}=await fixture(t,{proposals});
  assert.equal(await page.evaluate(()=>results.length),0);
  await page.getByRole('button',{name:'拒绝',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-proposal=new]').textContent.includes('已拒绝'));
  assert.equal(calls.find(x=>x.path.endsWith('/decision')).body.decision,'reject');
  assert.equal(await page.evaluate(()=>results.length),0);
  const separator=await page.locator('#studio-separator').boundingBox();
  await page.mouse.move(separator.x+4,separator.y+200);await page.mouse.down();await page.mouse.move(850,separator.y+200);await page.mouse.up();
  assert.equal(Math.round((await page.locator('#assistant-panel').boundingBox()).width),560);
});

test('中断的执行可显式标记未知结果，不宣称取消服务商请求',async t=>{
  const {page,calls}=await fixture(t,{proposals:[{id:'running',title:'执行建议',status:'executing'}]});
  await page.getByRole('button',{name:'标记执行结果未知',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-proposal=running]').textContent.includes('结果未知'));
  await page.waitForFunction(()=>document.querySelector('#assistant-notice').textContent.includes('不会取消'));
  assert.equal(calls.filter(x=>x.path.endsWith('/proposals/running/abandon')).length,1);
  assert.match(await page.locator('#assistant-notice').textContent(),/不会取消/);
});

test('选择工作区原文后引用，发送引用纯文本而不修改工作区',async t=>{
  const {page,calls}=await fixture(t);
  await page.evaluate(()=>{const range=document.createRange();range.selectNodeContents(document.querySelector('#old-workspace div'));const selected=getSelection();selected.removeAllRanges();selected.addRange(range);});
  await page.getByRole('button',{name:'引用选区',exact:true}).click();
  await page.locator('#assistant-input').fill('检查这段');await page.getByRole('button',{name:'发送消息',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#assistant-messages').textContent.includes('已读取'));
  assert.equal(calls.find(x=>x.path.endsWith('/messages')).body.context.selection,'工作区');
  assert.equal(await page.locator('#existing-input').inputValue(),'保留编辑');
});

test('HTTP 成功但模型结果未知时仍保留原请求恢复入口',async t=>{
  const {page,calls}=await fixture(t,{replyStatus:'unknown'});
  await page.locator('#assistant-input').fill('结果未知');await page.getByRole('button',{name:'发送消息',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#assistant-messages').textContent.includes('结果未知'));
  assert.equal(await page.locator('#assistant-retry').count(),1,'unknown model outcome retains explicit retry');
  assert.equal(calls.filter(x=>x.path.endsWith('/messages')).length,1);
});

test('接受创建建议后绑定同一会话并刷新新项目',async t=>{
  const {page}=await fixture(t,{project:null,proposals:[{id:'create',kind:'writer_create',title:'创建故事',status:'pending',available:true}]});
  await page.getByRole('button',{name:'接受并执行',exact:true}).click();
  await page.waitForFunction(()=>results.length===1,{},{timeout:5000});
  assert.equal(await page.evaluate(()=>ctx.project_id),'created-project');
  assert.equal(await page.locator('#studio-root').getAttribute('data-thread'),'thread-free');
  assert.match(await page.locator('#studio-nav a[data-stage=storyboard]').getAttribute('href'),/project=created-project/);
});

test('Agent 输入框随长草稿增高，换行与中文组合输入不发送，成功后复位',async t=>{
  const {page,calls}=await fixture(t);
  const input=page.locator('#assistant-input');
  const initial=(await input.boundingBox()).height;
  await input.fill(Array.from({length:14},(_,i)=>'镜头要求 '+i).join('\n'));
  assert.ok((await input.boundingBox()).height>initial+30,'long draft should expand the composer');
  assert.ok((await input.boundingBox()).height<=180,'long draft remains bounded');
  await input.press('Shift+Enter');
  await input.dispatchEvent('compositionstart');await input.press('Enter');
  assert.equal(calls.filter(x=>x.path.endsWith('/messages')).length,0);
  await input.dispatchEvent('compositionend');await input.press('Enter');
  await page.waitForFunction(()=>document.querySelector('#assistant-input').value==='');
  assert.equal(calls.filter(x=>x.path.endsWith('/messages')).length,1);
  assert.ok((await input.boundingBox()).height<=initial+2,'completed message resets composer height');
});

test('窄屏长模型名与用户长消息保持可操作、可滚动且不横向溢出',async t=>{
  const {page}=await fixture(t,{width:320});
  await page.locator('#assistant-model option').first().evaluate(o=>o.textContent='已配置的很长的真实文本模型名称 · 固定版本 V2');
  await page.locator('#assistant-input').fill('请检查镜头动作与空间关系。'.repeat(45));
  await page.getByRole('button',{name:'发送消息',exact:true}).click();
  await page.locator('.studio-message-user').waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  const panel=await page.locator('#assistant-panel').boundingBox();
  for(const selector of ['#assistant-model','#assistant-effort','#assistant-input','.studio-send']){
    const box=await page.locator(selector).boundingBox();
    assert.ok(box.x>=panel.x&&box.x+box.width<=panel.x+panel.width+1,selector+' fits assistant panel');
    assert.ok(box.y>=panel.y&&box.y+box.height<=panel.y+panel.height+1,selector+' remains visible');
  }
  const user=await page.locator('.studio-message-user').boundingBox();
  assert.ok(user.width<=panel.width-20,'long messages leave readable side space');
});

test('输入框随侧栏宽度重新排版，重载按保存宽度恢复合适高度',async t=>{
  const {page}=await fixture(t);
  const input=page.locator('#assistant-input'),separator=page.locator('#studio-separator');
  await separator.focus();await page.keyboard.press('End');
  await input.fill('让镜头中的动作和人物视线形成清楚的叙事关系。'.repeat(4));
  const wide=(await input.boundingBox()).height;
  await separator.focus();await page.keyboard.press('Home');
  await page.waitForFunction(h=>document.querySelector('#assistant-input').getBoundingClientRect().height>h+20,wide,{timeout:2000});
  await page.keyboard.press('End');
  await page.waitForFunction(h=>Math.abs(document.querySelector('#assistant-input').getBoundingClientRect().height-h)<2,wide);
  await page.reload();await page.waitForFunction(()=>document.querySelector('#assistant-status').textContent==='已连接');
  assert.equal(Math.round((await page.locator('#assistant-panel').boundingBox()).width),560);
  assert.ok(Math.abs((await input.boundingBox()).height-wide)<2,'saved width is applied before measuring restored draft');
});

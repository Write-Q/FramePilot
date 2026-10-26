const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');

async function videoInputs(page) {
  await page.evaluate(()=>{
    window.draft={shots:[{key:'shot-1',duration_ms:4000}]};window.selected=0;
    window.readMemory=k=>JSON.parse(sessionStorage.getItem(k)||'null');
    window.memory=(k,v)=>v===null?sessionStorage.removeItem(k):sessionStorage.setItem(k,JSON.stringify(v));
    window.StoryboardMedia={firstFrameSelected:()=>false};window.notice=()=>{};
  });
}

test('视频播放器、选用门禁、任务恢复和项目隔离',async()=>{
  assert.ok(fs.existsSync('app/static/storyboard-video.js'),'video module exists');
  const browser=await chromium.launch({headless:true,...(process.env.FRAMEPILOT_CHROME?{executablePath:process.env.FRAMEPILOT_CHROME}:{})});
  const page=await browser.newPage({viewport:{width:390,height:844}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  try {
    await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:fs.readFileSync('app/static/storyboard.html','utf8').replace(/<script[\s\S]*?<\/script>/g,'')}));
    await page.goto('http://localhost/storyboard');
    await page.addStyleTag({content:fs.readFileSync('app/static/storyboard.css','utf8')});
    await page.evaluate(()=>{
      window.$=id=>document.getElementById(id);window.project={id:'p'};window.current={id:'b',version:2,current_version:2,confirmed:true};window.working=false;window.dirty=false;window.readonly=()=>current.version!==current.current_version;
      window.node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
      window.prefix='/api/production';window.boardUrl=()=>'/boards/'+current.id;
      window.testRuns=[];window.requests=[];window.adapters={registered:[],media_validator_configured:false,capabilities_verified:false};
      window.api=async(url,body)=>{requests.push({url,body});return url.endsWith('video-adapters')?adapters:{runs:testRuns,selections:[]};};
      window.busy=async fn=>{working=true;StoryboardVideo.availability();try{await fn();}finally{working=false;StoryboardVideo.availability();}};
      $('board').hidden=false;
    });
    await videoInputs(page);
    await page.addScriptTag({content:fs.readFileSync('app/static/storyboard-video.js','utf8')});
    await page.evaluate(()=>StoryboardVideo.refresh());
    assert.match(await page.locator('#video-service-status').textContent(),/尚未接入视频服务/);
    assert.equal(await page.locator('#generate-video').isDisabled(),true,'缺少模型配置时不可生成');
    await page.evaluate(async()=>{testRuns=[{id:'q',status:'queued',shot_key:'shot-1',version:2},{id:'u',status:'unknown',shot_key:'shot-1',version:1,error:'<img src=x onerror=alert(1)>',external_id:'job-123'}];await StoryboardVideo.refresh();});
    assert.match(await page.locator('#video-runs').textContent(),/等待生成服务处理/);
    assert.match(await page.locator('#video-runs').textContent(),/不会自动重新提交/);
    assert.match(await page.locator('#video-runs').textContent(),/V1.*历史版本/);
    assert.equal(await page.locator('#video-runs img').count(),0,'错误内容不得执行 HTML');
    assert.equal(await page.evaluate(()=>requests.some(r=>r.body!==undefined)),false,'读取状态不提交任务');
    await page.evaluate(async()=>{
      testRuns=[{id:'candidate',status:'succeeded',shot_key:'shot-1',version:2,applicable:true,media_url:'/media/video.mp4',duration_ms:4000,output:{metadata:{width:1280,height:720,duration_ms:4500}}},
      {id:'unsafe',status:'succeeded',shot_key:'shot-2',version:2,applicable:true,media_url:'https://elsewhere.example/video.mp4'},
      {id:'old',status:'succeeded',shot_key:'shot-1',version:1,applicable:false,media_url:'/media/old.mp4'},
      {id:'q',status:'queued',shot_key:'shot-2',version:2},
      {id:'poll',status:'polling',shot_key:'shot-3',version:2,external_id:'job-fixed'}];
      await StoryboardVideo.refresh();
    });
    assert.equal(await page.locator('#video-runs video').count(),2,'只渲染同源视频');
    const player=page.locator('#video-runs video').first();
    assert.equal(await player.getAttribute('preload'),'metadata');
    assert.equal(await player.evaluate(video=>video.controls&&!video.autoplay),true);
    assert.match(await page.locator('#video-runs').textContent(),/1280 × 720/);
    assert.match(await page.locator('#video-runs').textContent(),/4.50 秒.*4.00 秒.*\+0.50 秒/);
    const choose=page.getByRole('button',{name:'选用此视频',exact:true});
    assert.equal(await choose.count(),2,'外部URL不提供选用');
    assert.equal(await choose.nth(1).isDisabled(),true,'旧版不可选');
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'含播放器的390px布局无溢出');
    await page.evaluate(()=>{current.confirmed=false;StoryboardVideo.availability();});
    assert.equal(await choose.first().isDisabled(),true,'未确认不可选');
    await page.evaluate(()=>{current.confirmed=true;StoryboardVideo.availability();});
    await page.evaluate(()=>{dirty=true;StoryboardVideo.availability();});
    assert.equal(await choose.first().isDisabled(),true);
    await page.evaluate(()=>{dirty=false;current.current_version=3;StoryboardVideo.availability();});
    assert.equal(await choose.first().isDisabled(),true,'只读不可选');
    await page.evaluate(()=>{current.current_version=2;StoryboardVideo.availability();});
    await choose.first().click();
    await page.waitForFunction(()=>!working);
    assert.deepEqual(await page.evaluate(()=>requests.filter(r=>r.body!==undefined).at(-1)),{url:'/boards/b/video-runs/candidate/select',body:{expected_version:2}});
    await page.getByRole('button',{name:'取消排队',exact:true}).click();
    await page.waitForFunction(()=>!working);
    assert.equal(await page.evaluate(()=>requests.filter(r=>r.body!==undefined).at(-1).url),'/boards/b/video-runs/q/cancel');
    assert.match(await page.locator('#video-runs').textContent(),/不会取消供应商/);
    await page.getByRole('button',{name:'恢复查询原任务',exact:true}).click();
    await page.waitForFunction(()=>!working);
    assert.equal(await page.evaluate(()=>requests.filter(r=>r.body!==undefined).at(-1).url),'/boards/b/video-runs/poll/recover-poll');
    await page.getByRole('button',{name:'标记结果未知',exact:true}).click();
    await page.waitForFunction(()=>!working);
    assert.equal(await page.evaluate(()=>requests.filter(r=>r.body!==undefined).at(-1).url),'/boards/b/video-runs/poll/abandon');
    await page.evaluate(()=>{project.id='other';StoryboardVideo.availability();});
    assert.equal(await page.locator('#video-runs article').count(),0,'切换项目立即隐藏旧记录');
    await page.evaluate(async()=>{testRuns=[];adapters={registered:['test-only'],media_validator_configured:false,capabilities_verified:false};await StoryboardVideo.refresh();});
    assert.match(await page.locator('#video-service-status').textContent(),/输出校验尚未配置/);
    assert.equal(await page.locator('#generate-video').isDisabled(),true,'注册状态不等于开放生成');
    await page.evaluate(async()=>{
      window.api=async url=>url.endsWith('video-adapters')?adapters:new Promise(resolve=>window.lateResolve=resolve);
      window.lateRefresh=StoryboardVideo.refresh();
      project.id='newer-project';StoryboardVideo.availability();
      lateResolve({runs:[{status:'running',version:2,shot_key:'旧项目镜头'}]});await lateRefresh;
    });
    assert.equal(await page.locator('#video-runs article').count(),0,'旧项目晚到响应不可重新显示');
    await page.evaluate(async()=>{window.api=async()=>{throw Error('连接失败');};await StoryboardVideo.refresh();});
    assert.match(await page.locator('#video-service-status').textContent(),/无法读取/);
    assert.match(await page.locator('#video-runs-status').textContent(),/无法读取/);
    assert.equal(await page.locator('#video-runs article').count(),0);
    await page.evaluate(()=>{
      StoryboardMedia.firstFrameSelected=()=>true;
      StoryboardVideo.setProfiles([{id:'ark',version:1,config:{purpose:'video',adapter:'ark_seedance',name:'test',model:'doubao-seedance-2-0-260128'}}]);
      $('video-cost-confirm').checked=true;StoryboardVideo.availability();
    });
    assert.equal(await page.locator('#generate-video').isDisabled(),true,'读取任务历史失败不能开放新生成');
    await page.evaluate(async()=>{
      project.id='p';
      memory('framepilot:video-pending:p:b',{expected_version:2,shot_key:'shot-1',profile:{profile_id:'ark',version:1},idempotency_key:'lost-response-key'});
      StoryboardVideo.availability();
      $('video-cost-confirm').checked=true;
      window.api=async url=>url.endsWith('video-adapters')?adapters:{runs:[{id:'done',version:2,shot_key:'shot-1',status:'failed',idempotency_key:'lost-response-key'}]};
      await StoryboardVideo.refresh();
    });
    assert.equal(await page.evaluate(()=>readMemory('framepilot:video-pending:p:b')),null,'刷新找到原任务后清除待恢复记录');
    assert.equal(await page.locator('#video-cost-confirm').isChecked(),false,'恢复已完成任务不能沿用上一次的费用授权');
    assert.equal(await page.locator('#generate-video').isDisabled(),true,'另一次生成必须重新确认');
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    assert.equal(await page.evaluate(()=>requests.filter(r=>r.body!==undefined).length),4,'只提交用户点击的操作');
    assert.deepEqual(errors,[]);
  }finally{await browser.close();}
});

async function inspectionFixture(t) {
  const browser=await chromium.launch({headless:true,...(process.env.FRAMEPILOT_CHROME?{executablePath:process.env.FRAMEPILOT_CHROME}:{})});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:390,height:844}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:fs.readFileSync('app/static/storyboard.html','utf8').replace(/<script[\s\S]*?<\/script>/g,'')}));
  await page.goto('http://localhost/storyboard');
  await page.addStyleTag({content:fs.readFileSync('app/static/storyboard.css','utf8')});
  await page.evaluate(()=>{
    window.$=id=>document.getElementById(id);window.project={id:'p'};window.current={id:'b',version:2,current_version:2,confirmed:true};window.working=false;window.dirty=false;window.readonly=()=>current.version!==current.current_version;
    window.node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
    window.prefix='/api/production';window.boardUrl=()=>'/boards/'+current.id;
    window.testRuns=[{id:'candidate',status:'succeeded',shot_key:'shot-1',version:2,applicable:true,media_url:'/media/video.mp4',duration_ms:4000}];
    window.testReport={id:'report-1',version:2,applicable:true,technical:{actual:{duration_ms:1000,width:1280,height:720},planned:{duration_ms:4000,aspect_ratio:'16:9'},warnings:['duration_mismatch'],semantic_review:'not_configured',audio_review:'not_performed'},frames:[{at_ms:250,url:'/evidence/first.jpg'},{at_ms:750,url:'https://elsewhere.example/frame.jpg'}],content_status:'pending',notes:[]};
    window.reports=[];window.requests=[];window.failInspection=0;window.failNote=0;window.testErrors=[];
    window.api=async(url,body)=>{
      requests.push({url,body:body===undefined?undefined:structuredClone(body)});
      if(url.endsWith('video-adapters'))return {registered:[],media_validator_configured:false};
      if(url.endsWith('/inspections')){
        if(body){if(failInspection-->0)throw Error('检查响应丢失');reports=[structuredClone(testReport)];return structuredClone(testReport);}
        return {reports:structuredClone(reports)};
      }
      if(url.endsWith('/notes')){
        if(failNote-->0)throw Error('记录响应丢失');
        if(window.rejectNote){const error=new Error('版本已失效');error.status=409;throw error;}
        reports[0].notes.push({...structuredClone(body),id:'note-1'});reports[0].content_status=body.decision;return structuredClone(reports[0]);
      }
      return {runs:structuredClone(testRuns),selections:[]};
    };
    window.busy=async fn=>{working=true;StoryboardVideo.availability();try{await fn();}catch(error){testErrors.push(error.message);}finally{working=false;StoryboardVideo.availability();}};
    $('board').hidden=false;
  });
  await videoInputs(page);
  await page.addScriptTag({content:fs.readFileSync('app/static/storyboard-video.js','utf8')});
  await page.evaluate(()=>StoryboardVideo.refresh());
  return {page,errors};
}

test('视频检查按需抽帧、定位证据并保存人工结论，不自动选用',async t=>{
  const {page,errors}=await inspectionFixture(t);
  assert.equal(await page.evaluate(()=>requests.some(request=>request.url.endsWith('/inspections'))),false,'载入候选不自动抽帧或读取全部报告');
  const inspect=page.getByRole('button',{name:'检查视频',exact:true});
  assert.equal(await inspect.count(),1);
  await inspect.click();await page.waitForFunction(()=>!working);
  const inspectionRequest=await page.evaluate(()=>requests.find(request=>request.url.endsWith('/inspections')&&request.body));
  assert.equal(inspectionRequest.url,'/boards/b/video-runs/candidate/inspections');
  assert.equal(inspectionRequest.body.count,8);
  assert.ok(inspectionRequest.body.idempotency_key);
  assert.match(await page.locator('#video-runs').textContent(),/待人工审核/);
  assert.match(await page.locator('#video-runs').textContent(),/抽帧.*不能.*完整/);
  assert.match(await page.locator('#video-runs').textContent(),/声音|音频/);
  assert.match(await page.locator('#video-runs').textContent(),/1280 × 720/);
  assert.match(await page.locator('#video-runs').textContent(),/实际 1.000 秒.*计划 4.000 秒/);
  assert.match(await page.locator('#video-runs').textContent(),/实际时长与计划不一致/);
  assert.equal(await page.locator('.video-inspection-frames img').count(),1,'证据图片只使用同源URL');
  const frame=page.getByRole('button',{name:'定位视频至 0.250 秒',exact:true});
  await frame.click();
  assert.equal(await page.locator('video').evaluate(video=>video.currentTime),0.25);
  assert.equal(await page.locator('video').evaluate(video=>video.paused),true,'点击证据不自动播放');
  await page.getByRole('button',{name:'添加时间区间发现',exact:true}).click();
  await page.getByLabel('开始（秒）',{exact:true}).fill('0.25');
  await page.getByLabel('结束（秒）',{exact:true}).fill('0.75');
  await page.getByLabel('问题描述',{exact:true}).fill('口型与台词不同步');
  await page.getByLabel('审核补充说明',{exact:true}).fill('已播放整段，建议修正声音。');
  await page.getByLabel('人工结论',{exact:true}).selectOption('needs_revision');
  await page.getByRole('button',{name:'保存人工结论',exact:true}).click();await page.waitForFunction(()=>!working);
  const noteRequest=await page.evaluate(()=>requests.find(request=>request.url.endsWith('/notes')));
  assert.equal(noteRequest.url,'/boards/b/video-runs/candidate/inspections/report-1/notes');
  assert.deepEqual({...noteRequest.body,idempotency_key:'key'},{expected_version:2,idempotency_key:'key',decision:'needs_revision',findings:[{start_ms:250,end_ms:750,severity:'medium',description:'口型与台词不同步'}],comment:'已播放整段，建议修正声音。'});
  assert.match(await page.locator('#video-runs').textContent(),/需修改/);
  assert.match(await page.locator('#video-runs').textContent(),/0.250.*0.750.*口型与台词不同步/);
  assert.equal(await page.evaluate(()=>requests.some(request=>request.url.endsWith('/select'))),false);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'报告及人工表单在390px无横向溢出');
  await page.setViewportSize({width:1440,height:1000});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'桌面报告布局无横向溢出');
  assert.deepEqual(errors,[]);
});

test('历史审核记录可读，未确认、未保存、失效版本不可创建检查或提交结论',async t=>{
  const {page,errors}=await inspectionFixture(t);
  const inspect=page.getByRole('button',{name:'检查视频',exact:true});
  for(const change of ['current.confirmed=false','current.confirmed=true;dirty=true','dirty=false;current.current_version=3']){
    await page.evaluate(code=>{eval(code);StoryboardVideo.availability();},change);
    assert.equal(await inspect.isDisabled(),true);
  }
  await page.evaluate(()=>{current.current_version=2;StoryboardVideo.availability();reports=[{...testReport,id:'history',version:1,applicable:false,content_status:'reviewed',notes:[{decision:'reviewed',comment:'旧版本已核对',findings:[]}]}];});
  await page.getByRole('button',{name:'查看审核记录',exact:true}).click();await page.waitForFunction(()=>!working);
  assert.match(await page.locator('#video-runs').textContent(),/历史.*只读|只读.*历史/);
  assert.match(await page.locator('#video-runs').textContent(),/旧版本已核对/);
  assert.equal(await page.getByRole('button',{name:'保存人工结论',exact:true}).count(),0);
  await page.evaluate(()=>{reports=[structuredClone(testReport)];});
  await page.getByRole('button',{name:'查看审核记录',exact:true}).click();await page.waitForFunction(()=>!working);
  await page.evaluate(()=>{dirty=true;StoryboardVideo.availability();});
  assert.equal(await page.getByRole('button',{name:'保存人工结论',exact:true}).isDisabled(),true);
  assert.equal(await page.getByLabel('审核补充说明',{exact:true}).isDisabled(),true);
  assert.equal(await page.getByRole('button',{name:'查看审核记录',exact:true}).isEnabled(),true);
  assert.equal(await page.evaluate(()=>requests.some(request=>request.body)),false);
  assert.deepEqual(errors,[]);
});

test('检查和人工记录在响应丢失后使用同一幂等键及原始内容恢复，4xx后允许改正',async t=>{
  const {page,errors}=await inspectionFixture(t);
  await page.evaluate(()=>{failInspection=1;});
  await page.getByRole('button',{name:'检查视频',exact:true}).click();await page.waitForFunction(()=>!working);
  assert.match(await page.locator('#video-runs').textContent(),/响应丢失|原请求/);
  await page.evaluate(()=>StoryboardVideo.refresh());
  await page.getByRole('button',{name:/恢复.*检查/}).click();await page.waitForFunction(()=>!working);
  const checks=await page.evaluate(()=>requests.filter(request=>request.url.endsWith('/inspections')&&request.body));
  assert.deepEqual(checks[0],checks[1],'刷新候选后仍使用同一检查请求');
  await page.getByLabel('审核补充说明',{exact:true}).fill('第一次提交的核对说明');
  await page.getByLabel('人工结论',{exact:true}).selectOption('reviewed');
  await page.evaluate(()=>{failNote=1;});
  await page.getByRole('button',{name:'保存人工结论',exact:true}).click();await page.waitForFunction(()=>!working);
  assert.equal(await page.getByLabel('审核补充说明',{exact:true}).isDisabled(),true,'待恢复请求锁定原始内容');
  await page.getByRole('button',{name:/恢复.*人工结论/}).click();await page.waitForFunction(()=>!working);
  const notes=await page.evaluate(()=>requests.filter(request=>request.url.endsWith('/notes')));
  assert.deepEqual(notes[0],notes[1]);
  await page.getByLabel('审核补充说明',{exact:true}).fill('将被拒绝的说明');
  await page.getByLabel('人工结论',{exact:true}).selectOption('reviewed');
  await page.evaluate(()=>{rejectNote=true;});
  await page.getByRole('button',{name:'保存人工结论',exact:true}).click();await page.waitForFunction(()=>!working);
  assert.equal(await page.evaluate(()=>requests.filter(request=>request.url.endsWith('/notes')).length),3,'明确拒绝确已发送第三次请求');
  assert.equal(await page.getByLabel('审核补充说明',{exact:true}).isEnabled(),true,'明确409清除待恢复状态');
  await page.getByLabel('审核补充说明',{exact:true}).fill('修正后的说明');
  await page.evaluate(()=>{rejectNote=false;});
  await page.getByRole('button',{name:'保存人工结论',exact:true}).click();await page.waitForFunction(()=>!working);
  const finalNotes=await page.evaluate(()=>requests.filter(request=>request.url.endsWith('/notes')));
  assert.notEqual(finalNotes.at(-1).body.idempotency_key,finalNotes.at(-2).body.idempotency_key);
  assert.equal(finalNotes.at(-1).body.comment,'修正后的说明');
  assert.deepEqual(errors,[]);
});

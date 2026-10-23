const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');

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
    await page.addScriptTag({content:fs.readFileSync('app/static/storyboard-video.js','utf8')});
    await page.evaluate(()=>StoryboardVideo.refresh());
    assert.match(await page.locator('#video-service-status').textContent(),/尚未接入视频服务/);
    assert.equal(await page.locator('#video-runtime-panel button').count(),1,'仅提供刷新操作');
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
    assert.equal(await page.locator('#video-runtime-panel button').count(),1,'注册状态不等于开放生成');
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
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    assert.equal(await page.evaluate(()=>requests.filter(r=>r.body!==undefined).length),4,'只提交用户点击的操作');
    assert.deepEqual(errors,[]);
  }finally{await browser.close();}
});

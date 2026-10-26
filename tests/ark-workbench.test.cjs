const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');

test('火山配置、首帧视频、丢失响应恢复与移动端',{timeout:90000},async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.FRAMEPILOT_CHROME?{executablePath:process.env.FRAMEPILOT_CHROME}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  try {
    await page.goto(process.env.FRAMEPILOT_UI_URL+'/storyboard?project='+process.env.FRAMEPILOT_PROJECT);
    await page.waitForFunction(()=>window.StoryboardVideo&&document.getElementById('board-state').textContent.includes('已确认')&&!document.body.classList.contains('busy'));
    await page.getByRole('button',{name:'图片素材',exact:true}).click();
    await page.locator('#image-config-details > summary').click();
    assert.equal(await page.locator('#image-config-adapter').inputValue(),'ark_seedream');
    assert.equal(await page.locator('#image-config-url').inputValue(),'https://ark.cn-beijing.volces.com/api/v3');
    assert.equal(await page.locator('#image-config-env').inputValue(),'ARK_API_KEY');
    assert.equal(await page.locator('#image-config-url').evaluate(el=>el.readOnly),true);
    await page.locator('#image-config-name').fill('火山图片测试');
    await page.locator('#image-config-model').fill('doubao-seedream-4-5-251128');
    await page.locator('#image-config-env').fill('TEST_ARK_KEY');
    await page.getByRole('button',{name:'保存图像配置',exact:true}).click();
    await page.waitForFunction(()=>!document.body.classList.contains('busy'));
    assert.equal(await page.locator('#image-size').inputValue(),'2560x1440');
    assert.ok(await page.locator('#media-candidates').textContent().then(s=>s.includes('已选用')));
    await page.getByRole('button',{name:'视频与检查',exact:true}).click();
    await page.locator('#video-config-details > summary').click();
    await page.locator('#video-config-name').fill('火山视频测试');
    await page.locator('#video-config-model').fill('doubao-seedance-2-0-260128');
    await page.locator('#video-config-env').fill('TEST_ARK_KEY');
    await page.getByRole('button',{name:'保存视频配置',exact:true}).click();
    await page.waitForFunction(()=>!document.body.classList.contains('busy'));
    assert.match(await page.locator('#video-profile-summary').textContent(),/720p.*无声/);
    assert.equal(await page.locator('#generate-video').isDisabled(),true);
    const submitted=[];
    let dropFirst=true;
    await page.route('**/video-runs',async route=>{
      if(route.request().method()!=='POST')return route.continue();
      submitted.push(route.request().postDataJSON());
      if(dropFirst){dropFirst=false;await route.fetch();await route.abort('failed');}
      else await route.continue();
    });
    await page.locator('#video-cost-confirm').check();
    assert.equal(await page.locator('#generate-video').isDisabled(),false);
    await page.locator('#generate-video').click();
    await page.getByRole('button',{name:'核对上次视频请求',exact:true}).waitFor();
    await page.waitForFunction(()=>!document.body.classList.contains('busy'));
    assert.equal(submitted.length,1,'未自动重发生成请求');
    await page.getByRole('button',{name:'核对上次视频请求',exact:true}).click();
    await page.waitForFunction(()=>!document.body.classList.contains('busy'));
    assert.equal(submitted.length,2);
    assert.deepEqual(submitted[0],submitted[1],'恢复固定原参数和幂等键');
    const deadline=Date.now()+15000;
    while(!await page.locator('#video-runs video').count()){
      assert.ok(Date.now()<deadline,'视频 worker 未完成');
      await page.locator('#refresh-videos').click();
      await page.waitForFunction(()=>!document.body.classList.contains('busy'));
      await page.waitForTimeout(100);
    }
    await page.waitForFunction(()=>document.querySelector('#video-runs video')?.videoWidth>0);
    assert.match(await page.locator('#video-runs').textContent(),/实际 4.00 秒/);
    await page.getByRole('button',{name:'选用此视频',exact:true}).click();
    await page.waitForFunction(()=>!document.body.classList.contains('busy'));
    assert.match(await page.locator('#video-runs').textContent(),/已选用/);
    fs.mkdirSync('.runtime/ark-browser',{recursive:true});
    await page.locator('#video-runtime-panel').screenshot({path:'.runtime/ark-browser/desktop.png'});
    await page.setViewportSize({width:390,height:844});
    await page.getByRole('button',{name:'工作区',exact:true}).click();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.locator('#video-runtime-panel').screenshot({path:'.runtime/ark-browser/mobile.png'});
    await page.getByRole('button',{name:'镜头',exact:true}).click();
    await page.locator('#edit-title').fill('待保存的新标题');
    await page.getByRole('button',{name:'视频与检查',exact:true}).click();
    await page.locator('#video-cost-confirm').check();
    assert.equal(await page.locator('#generate-video').isDisabled(),true,'未保存修改不能启动新生成');
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
});

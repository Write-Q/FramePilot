const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.FRAMEPILOT_CHROME?{executablePath:process.env.FRAMEPILOT_CHROME}:{})});
  try {
    const page=await browser.newPage();
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(process.env.VIDEO_TEST_URL);
    const workspace=page.getByRole('button',{name:'工作区',exact:true});
    if(await workspace.isVisible())await workspace.click();
    await page.getByRole('button',{name:'视频与检查',exact:true}).click();
    await page.locator('#video-runs video').waitFor();
    await page.waitForFunction(()=>document.querySelector('#video-runs video')?.readyState>=2);
    const duration=await page.locator('#video-runs video').evaluate(async v=>{await v.play();return v.duration;});
    assert.ok(duration>0.9&&duration<1.1);
    await page.waitForFunction(()=>document.querySelector('#video-runs video').currentTime>0.15);
    await page.locator('[data-video-action="inspect"]').first().click();
    await page.locator('.video-inspection-frames img').first().waitFor();
    assert.ok(await page.locator('.video-inspection-frames img').first().evaluate(i=>i.complete&&i.naturalWidth>0));
    await page.locator('.video-inspection-report[data-content-status="pending"]').waitFor();
    await page.locator('.video-inspection-form select').first().selectOption('reviewed');
    await page.getByLabel('审核补充说明').fill('本地测试片段已人工核对；不代表真实生成质量评测。');
    await page.locator('[data-video-action="note"]').first().click();
    await page.locator('.video-inspection-report[data-content-status="reviewed"]').waitFor();
    assert.equal(await page.getByRole('button',{name:'选用此视频',exact:true}).count(),1,'审核不得自动选用视频');
    await page.getByRole('button',{name:'选用此视频',exact:true}).click();
    await page.getByRole('button',{name:'已选用此视频',exact:true}).waitFor();
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

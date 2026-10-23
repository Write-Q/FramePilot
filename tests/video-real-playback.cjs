const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.FRAMEPILOT_CHROME?{executablePath:process.env.FRAMEPILOT_CHROME}:{})});
  try {
    const page=await browser.newPage();
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(process.env.VIDEO_TEST_URL);
    await page.locator('#video-runs video').waitFor();
    await page.waitForFunction(()=>document.querySelector('#video-runs video')?.readyState>=2);
    const duration=await page.locator('#video-runs video').evaluate(async v=>{await v.play();return v.duration;});
    assert.ok(duration>0.9&&duration<1.1);
    await page.waitForFunction(()=>document.querySelector('#video-runs video').currentTime>0.15);
    await page.getByRole('button',{name:'选用此视频',exact:true}).click();
    await page.getByRole('button',{name:'已选用此视频',exact:true}).waitFor();
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

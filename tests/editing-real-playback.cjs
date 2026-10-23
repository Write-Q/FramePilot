// No request stubs: every UI action reaches the isolated real PostgreSQL app.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {setTimeout: delay} = require('node:timers/promises');

(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.FRAMEPILOT_CHROME ? {executablePath: process.env.FRAMEPILOT_CHROME} : {})});
  try {
    const context = await browser.newContext({acceptDownloads: true});
    const page = await context.newPage();
    const errors = [], writes = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (request.method() === 'POST') writes.push(new URL(request.url()).pathname);
    });
    await page.goto(process.env.EDITING_TEST_URL);
    await page.waitForLoadState('networkidle');
    await page.evaluate(()=>document.querySelectorAll('main details.studio-tools').forEach(n=>n.open=true));
    await page.locator('#clips .clip').waitFor();
    assert.equal(await page.locator('#clips .clip').count(), 1);
    assert.match(await page.locator('#source-state').innerText(), /已确认/);
    assert.equal(await page.locator('#export').isEnabled(), false);
    if(process.env.EDITING_TEST_LOCAL_CLIP) {
      await page.locator('#clips .clip').getByRole('button',{name:/ 移除$/}).click();
      assert.equal(await page.locator('#clips .clip').count(),0);
      await page.getByLabel('本地视频文件',{exact:true}).setInputFiles(process.env.EDITING_TEST_LOCAL_CLIP);
      const uploaded=page.waitForResponse(r=>r.url().endsWith('/editing/local-clips')&&r.request().method()==='POST');
      await page.getByRole('button',{name:'上传本地视频',exact:true}).click();
      const response=await uploaded;assert.equal(response.status(),201);
      // Chromium can evict a fetch upload response from its inspector cache.
      // The application must finish consuming it and display the saved asset;
      // independently read the durable record through the real HTTP API.
      await page.getByRole('button',{name:'本地输入.mp4 加入时间线',exact:true}).waitFor();
      const assets=await context.request.get(new URL('local-clips',response.url()).href);
      const [asset]=await assets.json();assert.equal(asset.source,'local_upload');
      assert.equal(await page.locator('#clips .clip').count(),0,'Upload must not adopt the clip');
      await page.getByRole('button',{name:'本地输入.mp4 加入时间线',exact:true}).click();
      await page.locator('#clips .clip').waitFor();
      assert.match(await page.locator('#clips').innerText(),/本地导入/);
    }
    await page.locator('#clips [data-field="start_ms"]').fill('0.1');
    await page.locator('#clips [data-field="end_ms"]').fill('0.9');
    await page.locator('#clips [data-field="gain"]').fill('0.5');
    await page.getByRole('button', {name: '添加字幕', exact: true}).click();
    await page.locator('#subtitles [data-field="end_ms"]').fill('0.5');
    await page.getByLabel('字幕 1', {exact: true}).fill('本地浏览器成片验收');
    await page.getByLabel('音频文件', {exact: true}).setInputFiles(process.env.EDITING_TEST_AUDIO);
    await page.getByRole('button', {name: '上传 WAV', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#audio-state').textContent.includes('已上传 1 份音频'));
    await page.getByRole('button', {name: '添加音轨', exact: true}).click();
    await page.locator('#audio-tracks [data-field="gain"]').fill('0.4');
    await page.getByLabel('循环至片尾', {exact: true}).check();
    const savedResponse = page.waitForResponse(r => r.url().endsWith('/editing/timeline') && r.request().method() === 'POST');
    await page.getByRole('button', {name: '保存时间线新版本', exact: true}).click();
    assert.equal((await savedResponse).status(), 201);
    await page.waitForFunction(() => document.querySelector('#save-state').textContent.includes('V1 · 已保存'));
    const queueResponse = page.waitForResponse(r => r.url().endsWith('/editing/exports') && r.request().method() === 'POST');
    await page.getByRole('button', {name: '提交成片导出', exact: true}).click();
    const response = await queueResponse;
    assert.equal(response.status(), 201);
    const queued = await response.json();
    assert.equal(queued.status, 'queued');
    assert.equal(queued.accepted, false);
    await page.locator('#exports h3', {hasText: '排队等待'}).waitFor();
    assert.equal(await page.locator('#export-preview video').count(), 0);
    fs.writeFileSync(process.env.EDITING_TEST_QUEUED, JSON.stringify({id: queued.id}));
    const deadline = Date.now() + 35000;
    while (!fs.existsSync(process.env.EDITING_TEST_RENDERED)) {
      assert.ok(Date.now() < deadline, 'Default FFmpeg worker did not finish');
      await delay(50); // Test harness handoff, independent of application state.
    }
    assert.equal(JSON.parse(fs.readFileSync(process.env.EDITING_TEST_RENDERED, 'utf8')).status, 'succeeded');
    await page.getByRole('button', {name: '重新读取', exact: true}).click();
    await page.locator('#exports h3', {hasText: '渲染成功'}).waitFor();
    await page.waitForFunction(() => document.querySelector('#export-preview video')?.readyState >= 2);
    const video = page.getByLabel('导出成片预览', {exact: true});
    const playback = await video.evaluate(async element => {
      await element.play();
      return {duration: element.duration, width: element.videoWidth, height: element.videoHeight};
    });
    assert.ok(playback.duration > .7 && playback.duration < .95, JSON.stringify(playback));
    assert.equal(playback.width, 1280);
    assert.equal(playback.height, 720);
    await page.waitForFunction(() => document.querySelector('#export-preview video').currentTime > .15);
    const advancedTime = await video.evaluate(element => {element.pause(); return element.currentTime;});
    assert.match(await page.locator('#exports .status').innerText(), /未人工验收/);
    const mediaURL = await video.getAttribute('src');
    const full = await context.request.get(mediaURL);
    assert.equal(full.status(), 200);
    assert.match(full.headers()['content-type'], /video\/mp4/);
    const bytes = await full.body();
    const partial = await context.request.get(mediaURL, {headers: {Range: 'bytes=0-31'}});
    assert.equal(partial.status(), 206);
    assert.equal(partial.headers()['content-range'], `bytes 0-31/${bytes.length}`);
    assert.deepEqual(await partial.body(), bytes.subarray(0, 32));
    const link = page.getByRole('link', {name: '下载当前成片', exact: true});
    const downloadedHeaders = await context.request.get(await link.getAttribute('href'));
    assert.match(downloadedHeaders.headers()['content-disposition'], /attachment/);
    assert.equal(downloadedHeaders.headers()['content-type'], 'video/mp4');
    assert.deepEqual(await downloadedHeaders.body(), bytes);
    const downloadEvent = page.waitForEvent('download');
    await link.click();
    const downloaded = await downloadEvent;
    assert.equal(await downloaded.failure(), null);
    assert.match(downloaded.suggestedFilename(), /\.mp4$/);
    await downloaded.saveAs(process.env.EDITING_TEST_DOWNLOAD);
    assert.deepEqual(fs.readFileSync(process.env.EDITING_TEST_DOWNLOAD), bytes);
    await page.getByLabel(/^验收时间线/).fill('本地合成素材浏览器验收；不代表真实模型质量评测。');
    await page.getByRole('button', {name: '记录人工验收', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#exports .status')?.textContent === '已人工验收');
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.evaluate(()=>document.querySelectorAll('main details.studio-tools').forEach(n=>n.open=true));
    await page.waitForFunction(() => document.querySelector('#exports .status')?.textContent === '已人工验收');
    if(process.env.EDITING_TEST_LOCAL_CLIP && process.env.FRAMEPILOT_EDITING_SCREENSHOT)await page.screenshot({path:process.env.FRAMEPILOT_EDITING_SCREENSHOT,fullPage:true});
    assert.equal(await page.getByRole('button', {name: '记录人工验收', exact: true}).count(), 0);
    assert.equal(await page.locator('#clips [data-field="start_ms"]').inputValue(), '0.1');
    assert.equal(await page.locator('#clips [data-field="end_ms"]').inputValue(), '0.9');
    assert.equal(await page.getByLabel('字幕 1', {exact: true}).inputValue(), '本地浏览器成片验收');
    assert.equal(await page.locator('#audio-tracks [data-field="gain"]').inputValue(), '0.4');
    assert.equal(await page.getByLabel('循环至片尾', {exact: true}).isChecked(), true);
    assert.equal(await page.locator('#exports .export-item').count(), 1);
    assert.equal(await page.locator('#error').isVisible(), false);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({duration: playback.duration, advanced_time: advancedTime,
      download_bytes: bytes.length, range_status: partial.status(),
      timeline_saves: writes.filter(path => path.endsWith('/editing/timeline')).length,
      export_requests: writes.filter(path => path.endsWith('/editing/exports')).length,
      acceptance_requests: writes.filter(path => path.endsWith('/accept')).length}));
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});

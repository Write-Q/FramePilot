// Run through tests/test_writer_browser.py so each run gets an isolated PostgreSQL database.
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const base = process.env.FRAMEPILOT_UI_URL;
const story = '小禾把唯一的钥匙交给阿林。小禾随后用这把钥匙打开门。';
let browser;

before(async () => {
  assert.ok(base, 'Run via pytest tests/test_writer_browser.py');
  browser = await chromium.launch({headless:true,
    ...(process.env.FRAMEPILOT_CHROME ? {executablePath:process.env.FRAMEPILOT_CHROME} : {})});
});
after(async () => { await browser?.close(); });

async function create(page, input=story) {
  await page.locator('#story').fill(input);
  await page.locator('#create-form button').click();
  await page.locator('.issue-choice').waitFor();
  return page.locator('#project-id').inputValue();
}
async function refresh(page) {
  await Promise.all([
    page.waitForResponse(r => r.url().endsWith('/versions') && r.request().method()==='GET'),
    page.locator('#refresh').click(),
  ]);
}
async function load(page, id) {
  await page.locator('#project-id').fill(id);
  await Promise.all([
    page.waitForResponse(r => r.url().endsWith(`/api/projects/${id}/versions`)),
    page.locator('#load-form button').click(),
  ]);
}

test('项目意见隔离，返回原项目恢复自己的意见', async () => {
  const page=await browser.newPage();
  try {
    await page.goto(base);
    const original=await create(page);
    await page.locator('#feedback').fill('仅属于原项目的修改要求');
    await create(page, '另一个故事：'+story);
    assert.equal(await page.locator('#feedback').inputValue(), '');
    await page.locator('#feedback').fill('第二个项目自己的要求');
    await load(page, original);
    assert.equal(await page.locator('#feedback').inputValue(), '仅属于原项目的修改要求');
  } finally { await page.close(); }
});

test('刷新与重新载入后保留同一暂停点的逐条方案', async () => {
  const page=await browser.newPage();
  try {
    await page.goto(base);
    const id=await create(page);
    await page.locator('.issue-choice').selectOption('replace');
    await page.locator('.issue-replacement').fill('只补充归还钥匙，不修改其他句子');
    await page.locator('#feedback').fill('保持温暖结尾');
    await refresh(page);
    assert.equal(await page.locator('.issue-choice').inputValue(), 'replace');
    assert.equal(await page.locator('.issue-replacement').inputValue(), '只补充归还钥匙，不修改其他句子');
    assert.equal(await page.locator('#feedback').inputValue(), '保持温暖结尾');
    await page.reload();
    await load(page,id);
    assert.equal(await page.locator('.issue-choice').inputValue(), 'replace');
    assert.equal(await page.locator('.issue-replacement').inputValue(), '只补充归还钥匙，不修改其他句子');
  } finally { await page.close(); }
});

test('桌面和手机的底部校验提示可见且获得焦点', async () => {
  for (const viewport of [{width:1440,height:1000},{width:390,height:844}]) {
    const page=await browser.newPage({viewport});
    try {
      await page.goto(base);
      await create(page);
      await page.locator('.issue-choice').selectOption('adopt');
      await page.locator('#clarify').click();
      assert.equal(await page.locator('#action-message').count(),1);
      assert.match(await page.locator('#action-message').innerText(), /仅澄清不能采用修改建议/);
      const bounds=await page.locator('#action-message').boundingBox();
      assert.ok(bounds && bounds.y>=0 && bounds.y+bounds.height<=viewport.height);
      assert.equal(await page.locator('#action-message').evaluate(e=>e===document.activeElement),true);
      if(process.env.FRAMEPILOT_UI_ARTIFACTS){
        fs.mkdirSync(process.env.FRAMEPILOT_UI_ARTIFACTS,{recursive:true});
        await page.screenshot({path:path.join(process.env.FRAMEPILOT_UI_ARTIFACTS,`validation-${viewport.width}.png`)});
      }
    } finally { await page.close(); }
  }
});

test('成功提交后不会把上一暂停点意见恢复到新版本', async () => {
  const page=await browser.newPage();
  try {
    await page.goto(base);
    await create(page);
    await page.locator('.issue-choice').selectOption('replace');
    await page.locator('.issue-replacement').fill('补充钥匙归还过程');
    await page.locator('#feedback').fill('只改这一处');
    await page.locator('#revise').click();
    await page.waitForFunction(()=>document.querySelector('#summary').textContent.includes('版本 2'));
    await page.locator('#refresh').waitFor({state:'visible'});
    // Wait until render's version lookup finishes and busy() re-enables controls.
    await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);
    assert.equal(await page.locator('#feedback').inputValue(),'');
    assert.equal(await page.locator('.issue-choice').inputValue(),'');
    await refresh(page);
    assert.equal(await page.locator('.issue-choice').inputValue(),'');
    assert.equal(await page.locator('.issue-replacement').inputValue(),'');
  } finally { await page.close(); }
});

test('仅澄清不增加正文版本，但新暂停点不恢复已提交意见', async () => {
  const page=await browser.newPage();
  try {
    await page.goto(base);
    const id=await create(page);
    const previous=await (await page.request.get(`${base}/api/projects/${id}`)).json();
    await page.locator('.issue-choice').selectOption('keep');
    await page.locator('.issue-replacement').fill('这是后续才揭示的伏笔');
    await page.locator('#feedback').fill('仅解释设定，保留原稿');
    await Promise.all([
      page.waitForResponse(r=>r.url().endsWith(`/api/projects/${id}/versions`)),
      page.locator('#clarify').click(),
    ]);
    await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);
    const current=await (await page.request.get(`${base}/api/projects/${id}`)).json();
    assert.equal(current.state.version,previous.state.version);
    assert.equal(current.state.draft,previous.state.draft);
    assert.notEqual(current.interrupt.id,previous.interrupt.id);
    assert.equal(await page.locator('#feedback').inputValue(),'');
    assert.equal(await page.locator('.issue-choice').inputValue(),'');
    await refresh(page);
    assert.equal(await page.locator('.issue-replacement').inputValue(),'');
  } finally { await page.close(); }
});

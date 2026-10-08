const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context=vm.createContext({});
vm.runInContext(fs.readFileSync('app/static/presentation.js','utf8')+';globalThis.view=Presentation;',context);
const view=context.view;
test('审核说明转换完整字段，不替换单词片段',()=>{
 assert.equal(view.text('draft 与 original_story 不一致'),'当前剧本 与 用户原稿 不一致');
 assert.equal(view.text('drafting / my_draft'),'drafting / my_draft');
});
test('输入错误的嵌套字段和提示为中文',()=>{
 assert.equal(view.validation([{loc:['body','decisions',0,'issue_id'],type:'missing',msg:'Field required'}]),'处理方案 · 第 1 项 · 审核问题：请填写此项。');
 assert.equal(view.validation([{loc:['body','new_field'],type:'new_error',msg:'raw debug'}]),'输入项：内容不符合要求，请检查后重试。');
});
test('未知状态不会直接显示技术值',()=>{
 assert.equal(view.label({},'new_internal_state','状态待确认'),'状态待确认');
});

test('生成预览只转换审核说明，不改变剧本与引用',()=>{
 assert.equal(view.preview('description','draft 不一致'),'当前剧本 不一致');
 assert.equal(view.preview('draft','draft 是片名'),'draft 是片名');
 assert.equal(view.preview('text','original_story 是道具上的字'),'original_story 是道具上的字');
});
test('用户决策原文保留，AI建议转换，未知选项有兜底',()=>{
 assert.equal(view.decision({choice:'replace',instruction:'保留 draft 字样'}),'替换建议：保留 draft 字样');
 assert.equal(view.decision({choice:'adopt',instruction:'修改 draft'}),'采用建议：修改 当前剧本');
 assert.equal(view.decision({choice:'future',instruction:'原文'}),'其他处理：原文');
});
test('常见配置和网络错误转成可操作说明',()=>{
 assert.ok(!view.error('未找到 DEEPSEEK_API_KEY').includes('DEEPSEEK_API_KEY'));
 assert.ok(view.error('模型未返回 JSON 对象').includes('格式'));
 assert.ok(view.error('Failed to fetch').includes('本地服务'));
});

const $ = id => document.getElementById(id);
let project = null;
const labels = {theme:'主题与情绪',characters:'人物',plot:'剧情',props:'道具',scenes:'场景',actions:'动作与表演',camera:'镜头语言',visual_style:'视觉风格',sound:'声音',pacing:'节奏与规格'};
const sources = {original:'原稿明确',user:'用户指定',ai_suggestion:'AI 建议',unknown:'尚未确定'};
const statuses = {awaiting_input:'等待补充',awaiting_confirmation:'等待确认',confirmed:'已确认',limit_reached:'已达修订上限',budget_exhausted:'调用额度不足',failed:'执行失败',running:'执行中',no_progress:'自动修订无进展',awaiting_direction:'等待选择方向',ready_for_production:'原稿待交接'};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'输入格式有误，请检查必填内容。');return data;}
async function busy(fn){$('error-panel').hidden=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);$('message').textContent='正在处理，请勿重复提交。模型调用可能需要一两分钟。';try{await fn();}catch(e){$('message').textContent=e.message;showError(e.message);}finally{document.querySelectorAll('button').forEach(b=>b.disabled=false);}}
async function render(value){
 if(project?.id!==value.id)activeFacet='theme';project=value;const s=value.state;
 $('output').hidden=false;$('project-id').value=value.id;localStorage.setItem('framepilot:last-project',value.id);
 $('message').textContent=s.error||s.stop_reason||'请审阅当前版本。';$('error-panel').hidden=true;if(s.error)showError(s.error);
 const modes={direct:'原稿直接制作',collaborative:'协作创作',free:'自由编剧',faithful:'旧版忠于原稿'};
 $('summary').textContent=`${modes[s.mode]} · ${statuses[s.status]||s.status} · 版本 ${s.version} · 修订 ${s.revision_count}/3 · 请求 ${value.calls_used}/${value.max_calls}`;
 $('retry').hidden=s.status!=='failed'||value.calls_used>=value.max_calls;$('identifier').textContent='项目编号：'+value.id;$('draft').textContent=s.draft;
 $('original').textContent=s.original_story;$('outline').textContent=s.outline||'尚未生成故事骨架。';
 $('facet-dock').hidden=!Object.keys(s.card||{}).length;renderFacetTabs(s.card||{});
 renderDirections(s);$('issues').replaceChildren();
 if(s.mode==='direct')$('issues').append(el('p','原稿未经过故事审核。可导出后交给制作环节，当前尚未连接视频平台。'));
 else if(s.status==='awaiting_direction')$('issues').append(el('p','选定方向并写出剧本后，再审核故事合理性。'));
 else if(s.reviewed_version!==s.version)$('issues').append(el('p','当前版本尚未完成有效审核。'));
 else if(!s.issues.length)$('issues').append(el('p','本次审核未发现待处理问题，仍请人工检查。'));
 for(const issue of s.issues){
   const box=el('article',undefined,'issue');box.dataset.issueId=issue.id;
   box.append(el('span',categories[issue.category]||'待审阅','badge'),el('strong',issue.description),el('p',issue.suggestion,'suggestion'));
   if(issue.carried_forward)box.append(el('p',`未处理项，依据来自版本 ${issue.version}，尚未因新版生成而视为接受。`,'hint'));
   appendRelated(box,issue);if(issue.evidence?.length)box.append(evidenceDetails(issue.evidence));
   if(s.mode==='collaborative'&&value.interrupt&&s.status!=='awaiting_direction'){
     const label=el('label','这条建议怎么处理？');const select=el('select');select.className='issue-choice';select.setAttribute('aria-label','处理建议：'+issue.description);
     for(const [key,text] of [['','暂不处理'],['adopt','采用 AI 修改建议'],['replace','用我的方案替换'],['keep','保留原设定，解释原因']]){const option=el('option',text);option.value=key;select.append(option);}
     const input=el('textarea');input.className='issue-replacement';input.maxLength=1500;input.rows=2;input.hidden=true;input.setAttribute('aria-label','你的方案或保留理由：'+issue.description);
     select.onchange=()=>{input.hidden=!['replace','keep'].includes(select.value);input.placeholder=select.value==='keep'?'说明为什么保留，系统会重新审核解释。':'写下你希望如何修改，替代 AI 原建议。';};
     label.append(select);box.append(label,input);
   }
   if(issue.needs_user||issue.category==='constraint')box.append(el('small','需要澄清或修订后重新审核'));
   else{const label=el('label');const cb=el('input');cb.type='checkbox';cb.value=issue.id;cb.name='accept-issue';label.append(cb,document.createTextNode(' 确认时接受此问题并保留现状（不采用修改建议）'));box.append(label);}
   $('issues').append(box);
 }
 const choosing=s.status==='awaiting_direction';$('actions').hidden=!value.interrupt||choosing;
 $('confirm').hidden=s.reviewed_version!==s.version||s.issues.some(i=>i.needs_user||i.category==='constraint');
 $('revise').textContent=s.mode==='collaborative'?'按所选方案修改并审核':'按补充要求修改并审核';
 $('feedback').placeholder=s.mode==='collaborative'?'可选：补充跨卡片的整体要求；逐条方案请在上方选择。':'说明新的要求、需要修改的内容，或要澄清的设定。';
 $('mode-help').textContent=s.mode==='collaborative'?'逐条选择不会立即改稿。统一提交后生成新版；仅解释设定请用“仅澄清并复审”。':'自由编剧会在约束内自动修订；仅澄清只重新审核，不改稿。';
 $('decision-history').replaceChildren();
 for(const entry of s.decision_history||[]){const d=el('details');d.append(el('summary',`版本 ${entry.version} · ${{revise:'修改',clarify:'澄清',choose:'选择方向'}[entry.action]||entry.action}`),el('p',entry.feedback));for(const item of entry.decisions||[])d.append(el('p',`${{adopt:'采用建议',replace:'替换建议',keep:'保留设定'}[item.choice]}：${item.instruction}`));$('decision-history').append(d);}
 $('versions').replaceChildren();const versions=await api(`/api/projects/${value.id}/versions`);
 for(const v of versions){const d=el('details');d.append(el('summary',`版本 ${v.version}`),el('pre',v.draft));if(v.version>1){const button=el('button','与上一版对比','secondary');button.type='button';const diff=el('pre');diff.hidden=true;button.onclick=()=>busy(async()=>{const result=await api(`/api/projects/${value.id}/diff?from_version=${v.version-1}&to_version=${v.version}`);diff.textContent=result.diff||'正文没有变化。';diff.hidden=false;});d.append(button,diff);}$('versions').append(d);}
 $('export').href=`/api/projects/${value.id}/export`;
}
function renderDirections(state){
 $('directions').replaceChildren();$('directions-panel').hidden=state.status!=='awaiting_direction';
 for(const option of state.directions||[]){const label=el('label',undefined,'direction');const radio=el('input');radio.type='radio';radio.name='direction';radio.value=option.id;label.append(radio,el('strong',option.title),el('p',option.outline));$('directions').append(label);}
}
function selectedDecisions(){
 return [...document.querySelectorAll('.issue-choice')].filter(select=>select.value).map(select=>({issue_id:select.closest('.issue').dataset.issueId,choice:select.value,text:select.closest('.issue').querySelector('.issue-replacement').value.trim()}));
}
$('create-form').addEventListener('submit',e=>{e.preventDefault();busy(async()=>{await render(await streamApi('/api/projects/stream',{story:$('story').value,mode:$('mode').value,constraints:$('constraints').value}));});});
$('load-form').addEventListener('submit',e=>{e.preventDefault();$('live').hidden=true;busy(async()=>render(await api('/api/projects/'+encodeURIComponent($('project-id').value.trim()))));});
$('retry').onclick=()=>busy(async()=>render(await streamApi(`/api/projects/${project.id}/retry/stream`,{})));
$('refresh').onclick=()=>busy(async()=>render(await api('/api/projects/'+project.id)));
async function resume(action){
 if(!project?.interrupt)return;
 const decisions=['revise','clarify'].includes(action)?selectedDecisions():[];
 const feedback=action==='confirm'?'':(action==='choose'?$('direction-feedback').value:$('feedback').value).trim();
 const direction_id=document.querySelector('[name="direction"]:checked')?.value||'';
 if(action==='choose'&&!direction_id){$('message').textContent='请先选择一个故事方向。';return;}
 if(['revise','clarify'].includes(action)&&!feedback&&!decisions.length){$('message').textContent='请选择建议或填写补充内容。';return;}
 if(decisions.some(d=>['replace','keep'].includes(d.choice)&&!d.text)){$('message').textContent='请填写替代方案或保留理由。';return;}
 if(action==='clarify'&&decisions.some(d=>d.choice!=='keep')){$('message').textContent='仅澄清不能采用修改建议，请改用“按所选方案修改并审核”。';return;}
 if(action==='confirm'&&(selectedDecisions().length||$('feedback').value.trim())){$('message').textContent='还有未提交的修改或澄清，请先提交，或清空后确认当前版本。';return;}
 await busy(async()=>{const result=await streamApi(`/api/projects/${project.id}/resume/stream`,{version:project.state.version,interrupt_id:project.interrupt.id,action,feedback,decisions,direction_id,accepted_issue_ids:[...document.querySelectorAll('[name="accept-issue"]:checked')].map(n=>n.value)});await render(result);$('feedback').value='';});
}
$('revise').onclick=()=>resume('revise');$('confirm').onclick=()=>resume('confirm');
$('clarify').onclick=()=>resume('clarify');$('choose-direction').onclick=()=>resume('choose');
$('project-id').value=localStorage.getItem('framepilot:last-project')||'';


async function streamApi(url, body) {
  $('live').hidden=false; $('output').hidden=true; $('live-text').textContent=''; $('live-stage').textContent='正在连接…';
  const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!response.ok){let data;try{data=await response.json();}catch{}const detail=data?.detail;const message=typeof detail==='string'?detail:Array.isArray(detail)?detail.map(e=>(e.loc||[]).filter(k=>k!=='body').join('.')+'：'+e.msg).join('；'):`请求失败（HTTP ${response.status}），请稍后重试。`;throw new Error(message);}
  const reader=response.body.getReader(), decoder=new TextDecoder();
  let pending='', result=null, generated='';
  try {
    while(true){
      const {value,done}=await reader.read();
      pending+=decoder.decode(value||new Uint8Array(),{stream:!done});
      let boundary;
      while((boundary=pending.indexOf('\n\n'))>=0){
        const frame=pending.slice(0,boundary);pending=pending.slice(boundary+2);
        for(const line of frame.split('\n')){
          if(!line.startsWith('data: '))continue;
          const item=JSON.parse(line.slice(6)), data=item.data;
          if(item.event==='project'){
            $('project-id').value=data.id;localStorage.setItem('framepilot:last-project',data.id);
          }else if(item.event==='stage'){
            generated='';$('live-text').textContent='正在整理内容…';
            $('live-stage').textContent=({brainstorm:'提出候选故事方向',plan:'构思故事骨架',compose:'编写完整剧本',extract:'提取故事卡片',review:'审核连续性与合理性',revise:'修订故事'})[data.task]||data.task;
          }else if(item.event==='delta'){
            generated+=data.text;renderPreview(generated);
          }else if(item.event==='error'){throw new Error(data.message);
          }else if(item.event==='result'){result=data;}
        }
      }
      if(done)break;
    }
    if(!result)throw new Error('连接中断；任务可能仍在执行，请使用项目编号载入结果，勿重复提交。');
    $('live-stage').textContent=result.state.status==='failed'?'执行失败，请查看错误说明':'本轮结束，正式结果见下方';
    if(!['failed','budget_exhausted'].includes(result.state.status))$('live').hidden=true;
    return result;
  }catch(error){if(project)$('output').hidden=false;$('live-stage').textContent='流已结束或断开；可通过项目编号重新载入。';throw error;}
  finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
}

const categories={missing:'信息待补充',continuity:'连续性待核对',constraint:'与创作要求不符',creative:'创作建议'};
function evidenceDetails(items){
 const details=el('details',undefined,'evidence');details.append(el('summary','查看依据'));
 for(const item of items)details.append(el('blockquote',item.quote));
 return details;
}
function renderPreview(raw){
 // 只解码已经闭合的 JSON 字符串；不展示字段名或猜测未完成的 JSON。
 const pattern=/"(title|outline|text|description|suggestion|draft)"\s*:\s*("(?:[^"\\]|\\.)*")/g;
 const fragment=document.createDocumentFragment();let match,count=0;
 while((match=pattern.exec(raw))!==null){
   try{
     const value=JSON.parse(match[2]);if(!value.trim())continue;
     const section=el('div',undefined,'preview-item');
     const names={title:'故事方向',outline:'故事骨架',text:'故事要素',description:'正在核对',suggestion:'建议方向',draft:'故事草稿'};
     section.append(el('small',names[match[1]]),el('p',value));fragment.append(section);count++;
   }catch{}
 }
 if(count)$('live-text').replaceChildren(fragment);
 else $('live-text').textContent='正在整理内容，完成一个要点后会在这里展示…';
}

let activeFacet='theme';
function selectFacet(key,issue=null,focus=false){
 if(!project?.state.card?.[key])return;
 activeFacet=key;
 document.querySelectorAll('[role="tab"]').forEach(tab=>{
   const selected=tab.dataset.facet===key;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;
 });
 document.querySelectorAll('.facet[role="tabpanel"]').forEach(panel=>panel.hidden=panel.dataset.facet!==key);
 $('facet-context').hidden=!issue;$('facet-context').textContent=issue?'正在查看建议：'+issue.description:'';
 if(focus){const tab=$('tab-'+key);tab.focus({preventScroll:true});$('facet-tabs').scrollIntoView({block:'start',behavior:'instant'});}
}
function renderFacetTabs(card){
 $('card').replaceChildren();$('facet-tabs').replaceChildren();$('facet-context').hidden=true;
 const keys=Object.keys(labels).filter(key=>card[key]);
 $('facet-tabs').hidden=!keys.length;
 if(!keys.length){$('card').append(el('p','故事卡片尚未生成成功，请查看上方错误说明。'));return;}
 for(const key of keys){
   const tab=el('button',labels[key],'facet-tab');tab.type='button';tab.id='tab-'+key;tab.dataset.facet=key;
   tab.setAttribute('role','tab');tab.setAttribute('aria-controls','panel-'+key);tab.onclick=()=>selectFacet(key);
   tab.onkeydown=event=>{let next=keys.indexOf(key);if(event.key==='ArrowRight')next=(next+1)%keys.length;else if(event.key==='ArrowLeft')next=(next+keys.length-1)%keys.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=keys.length-1;else return;event.preventDefault();selectFacet(keys[next]);$('tab-'+keys[next]).focus();};
   $('facet-tabs').append(tab);
   const facet=card[key],panel=el('section',undefined,'facet');panel.id='panel-'+key;panel.dataset.facet=key;panel.tabIndex=0;
   panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',tab.id);
   panel.append(el('strong',labels[key]),el('small',sources[facet.source]||facet.source),el('p',facet.text));
   if(facet.evidence)panel.append(evidenceDetails([{quote:facet.evidence}]));$('card').append(panel);
 }
 selectFacet(keys.includes(activeFacet)?activeFacet:keys[0]);
}
function appendRelated(box,issue){
 const keys=[...new Set(issue.related_facets||[])].filter(key=>Object.hasOwn(labels,key));
 if(!keys.length){box.append(el('small','此条建议暂无卡片关联，可通过上方标签查看。'));return;}
 const row=el('div',undefined,'related-facets');row.append(el('span','相关内容：'));
 for(const key of keys){
   if(!project.state.card?.[key]){row.append(el('span',labels[key]+'（尚未生成）'));continue;}
   const link=el('button',labels[key],'related-link');link.type='button';link.onclick=()=>selectFacet(key,issue,true);row.append(link);
 }box.append(row);
}

function updateEntryLabel(){
 const mode=$('mode').value;
 document.querySelector('#create-form button').textContent=mode==='direct'?'保留原稿并准备导出':mode==='free'?'开始自由编剧':'理解故事并协作创作';
}
$('mode').addEventListener('change',updateEntryLabel);updateEntryLabel();

function showError(message){
 const raw=String(message||'未知错误');let explanation=raw;
 if(raw.includes('来源引用')||raw.includes('不存在的原文')){
   const facet=Object.keys(labels).find(key=>raw.includes(' '+key+' '));
   explanation=`AI 返回的${facet?labels[facet]+'卡片':'审核结果'}包含无法在原文中核对的引用，因此本次结果没有通过校验。这不是要求你修改原稿。`;
 }
 $('error-explanation').textContent=explanation;$('error-detail').textContent=raw;
 $('error-next').textContent='可先载入或刷新项目查看已保存版本。若出现“重试失败步骤”按钮，可在剩余额度内重试；重试会消耗模型调用。';
 $('error-panel').hidden=false;
 requestAnimationFrame(()=>{$('error-panel').scrollIntoView({block:'start',behavior:'instant'});$('error-panel').focus({preventScroll:true});});
}

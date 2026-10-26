'use strict';
const $ = id => document.getElementById(id);
const prefix = '/api/production';
let project = null, boards = [], current = null, draft = null, selected = 0, dirty = false, working = false;
let rawFields = new Map();
const copy = value => JSON.parse(JSON.stringify(value));
const node = (tag, text, cls) => { const el = document.createElement(tag); if(text !== undefined) el.textContent=text; if(cls) el.className=cls; return el; };
const readMemory = key => { try { return JSON.parse(sessionStorage.getItem(key)||'null'); } catch { return null; } };
function memory(key,value) { try { if(value===null)sessionStorage.removeItem(key);else sessionStorage.setItem(key,JSON.stringify(value)); } catch {} }
function remember(key,value) { try { localStorage.setItem(key,value); } catch {} }
function last(key) { try { return localStorage.getItem(key)||''; } catch { return ''; } }
const scope = () => current ? `framepilot:board-draft:${current.project_id}:${current.id}` : '';
const pendingScope = () => `framepilot:board-pending:${project?.id}`;
const base = () => `${prefix}/projects/${encodeURIComponent(project.id)}`;
const boardUrl = () => `${base()}/storyboards/${encodeURIComponent(current.id)}`;
const readonly = () => !current || current.version !== current.current_version || !current.source_current || !current.source_confirmed;
function error(message) { $('error').textContent=message; $('error').hidden=false; }
function notice(message) { $('message').textContent=message; }
async function api(url, body) {
  const response = await fetch(url, body===undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  let data; try { data=await response.json(); } catch { throw new Error('服务未返回有效响应。生成请求可能仍在执行，请刷新运行记录。'); }
  if(!response.ok){const e=new Error(Presentation.validation(data.detail));e.status=response.status;throw e;}
  return data;
}
function availability() {
  const editingLink = $('editing-link');
  if(editingLink) {
    editingLink.hidden = !current;
    if(current) editingLink.href = '/editing?project=' + encodeURIComponent(project.id) + '&board=' + encodeURIComponent(current.id);
  }
  const pending=project&&readMemory(pendingScope());
  $('generate').disabled=working || !project || project.state.status!=='confirmed' || project.state.mode==='direct' || project.state.reviewed_version!==project.state.version || !$('profile').value;
  for(const el of $('shot-form').querySelectorAll('input,textarea,select'))el.disabled=working||readonly();
  $('edit-title').disabled=working||readonly();
  for(const id of ['save-board','add-shot','move-up','move-down','delete-shot'])$(id).disabled=working||readonly();
  $('save-board').disabled=working||readonly()||!dirty;
  $('move-up').disabled=working||readonly()||selected===0;
  $('move-down').disabled=working||readonly()||!draft||selected===draft.shots.length-1;
  $('delete-shot').disabled=working||readonly()||!draft||draft.shots.length<=1;
  $('add-shot').disabled=working||readonly()||!draft||draft.shots.length>=100;
  $('confirm-board').disabled=working||readonly()||dirty||!!current?.confirmed||!$('review-read').checked;
  $('dirty-state').textContent=dirty?'有未保存修改':'已保存';
  $('generate').textContent=pending?'恢复上次请求':'生成分镜草案';
  if(pending){
    const value=pending.profile.profile_id+':'+pending.profile.version;
    if(![...$('profile').options].some(option=>option.value===value)){const option=node('option','上次请求的固定配置 · V'+pending.profile.version);option.value=value;$('profile').append(option);}
    $('profile').value=value;$('target-shots').value=pending.target_shots;$('aspect-ratio').value=pending.aspect_ratio;
    $('visual-style').value=pending.visual_style;$('instructions').value=pending.instructions;
  }
  for(const id of ['profile','target-shots','aspect-ratio','visual-style','instructions'])$(id).disabled=working||!!pending;
  ModelPicker.sync('profile','effort',{pending,disabled:working});
  window.StoryboardReview?.availability();
  window.StoryboardMedia?.availability();
  window.StoryboardVideo?.availability();
  window.dispatchEvent(new Event('framepilot:studio-context'));
}
async function busy(operation) {
  if(working)return;
  working=true; $('error').hidden=true; document.body.classList.add('busy');
  document.querySelector('main').querySelectorAll('button,select').forEach(el=>el.disabled=true); availability();
  try { await operation(); } catch(e) { error(e.message); }
  finally { working=false; document.body.classList.remove('busy'); document.querySelector('main').querySelectorAll('button,select').forEach(el=>el.disabled=false); availability(); }
}
function markDirty() {
  dirty=true; $('review-read').checked=false;
  memory(scope(),{version:current.version,content:draft,raw:Object.fromEntries(rawFields)}); availability();
}
function allowDiscard() { return !dirty || window.confirm('当前分镜有未保存修改，确定放弃这些修改吗？'); }
async function profiles(selectId, purpose='text') {
  const items=await api(prefix+'/model-profiles');
  ModelPicker.setModels('profile','effort',items.filter(x=>x.config.purpose==='text'&&x.config.adapter==='openai_chat'),purpose==='text'?selectId:null);
  window.StoryboardReview?.setProfiles(items,purpose==='review'?selectId:null);
  window.StoryboardMedia?.setProfiles(items,purpose==='image'?selectId:null);
  window.StoryboardVideo?.setProfiles(items,purpose==='video'?selectId:null);
  availability();
}
async function loadProject(id) {
  if(!allowDiscard())return;
  const value=await api('/api/projects/'+encodeURIComponent(id));
  project=value; current=null; draft=null; dirty=false;
  $('project-id').value=id; remember('framepilot:last-project',id);
  const url=new URL(location.href); url.searchParams.set('project',id); history.replaceState(null,'',url);
  $('source-state').textContent=`剧本 V${value.state.version} · ${value.state.status==='confirmed'?'已确认':'尚未确认，需先返回编剧工作台'}${value.state.mode==='direct'?' · 原稿直送尚未审核':''}`;
  $('source-body').textContent=value.state.draft;
  $('board').hidden=true; $('empty').hidden=false;
  await profiles(); await refreshRuns(); await refreshBoards();
  const requestedBoard=new URL(location.href).searchParams.get('board');
  const identity=requestedBoard||last('framepilot:last-board:'+id);
  if(boards.length)await openBoard(boards.find(x=>x.id===identity)?.id||boards[boards.length-1].id);
  notice('剧本已载入。可生成新分镜，或继续编辑已有方案。');
}
async function refreshBoards() {
  boards=await api(base()+'/storyboards'); $('board-series').replaceChildren();
  for(const item of boards) { const opt=node('option',item.content.title+' · V'+item.version); opt.value=item.id; $('board-series').append(opt); }
  if(current&&boards.some(item=>item.id===current.id))$('board-series').value=current.id;
}
async function openBoard(identity, version) {
  const path=base()+'/storyboards/'+encodeURIComponent(identity)+(version?'/versions/'+version:'');
  current=await api(path); draft=copy(current.content); dirty=false; selected=0;rawFields=new Map();
  const saved=readMemory(scope());
  if(!readonly()&&saved?.version===current.version&&saved.content?.shots?.length) { draft=saved.content;rawFields=new Map(Object.entries(saved.raw||{}));dirty=true; notice('已恢复本标签页未保存的分镜修改，请核对后保存。'); }
  const studioUrl=new URL(location.href);studioUrl.searchParams.set('board',identity);history.replaceState(null,'',studioUrl);
  remember('framepilot:last-board:'+project.id,identity); $('board-series').value=identity;
  $('empty').hidden=true; $('board').hidden=false; $('edit-title').value=draft.title;
  $('board-title').textContent=current.content.title; $('board-version').textContent='V'+current.version;
  $('board-state').textContent=readonly()?(current.version!==current.current_version?'历史版本 · 只读':'来源剧本已变化或尚未确认 · 需重新交接'):(current.confirmed?'已确认 · 当前版本':'待确认 · 请逐镜审阅');
  $('board-stats').textContent=`${draft.shots.length} 镜 · ${(draft.shots.reduce((n,s)=>n+s.duration_ms,0)/1000).toFixed(1)} 秒计划时长 · ${draft.aspect_ratio} · 来源剧本 V${current.source_version}`;
  $('provenance').textContent=JSON.stringify({source_version_id:current.source_version_id,creation_method:current.creation_method,provenance:current.provenance},null,2);
  $('history-version').replaceChildren();
  for(let i=current.current_version;i>=1;i--) { const option=node('option',`V${i}${i===current.current_version?' · 当前版':' · 历史'}`); option.value=String(i); $('history-version').append(option); }
  $('history-version').value=String(current.version); $('review-read').checked=false;
  renderShots(); renderEditor(); await showReview(); await window.StoryboardReview?.refresh(); await window.StoryboardMedia?.refresh(); await window.StoryboardVideo?.refresh(); availability();
}
function renderShots() {
  $('shots').replaceChildren();
  draft.shots.forEach((shot,index)=>{
    const button=node('button',undefined,'shot-card'); button.type='button'; button.setAttribute('aria-pressed',String(selected===index));
    button.append(node('strong',`${String(index+1).padStart(2,'0')} / ${shot.shot_size||'景别待定'} · ${shot.duration_ms/1000}s`),node('span',shot.purpose),node('span',shot.action));
    const thumb=window.StoryboardMedia?.thumbnail(shot.key);if(thumb)button.append(thumb);
    button.onclick=()=>{if(!$('shot-form').reportValidity())return;selected=index;renderShots();renderEditor();availability();}; $('shots').append(button);
  });
}
const sections=[
  ['叙事与表演', [['scene_key','所属场次','scene'],['duration_ms','规划时长（秒）','seconds'],['source_quote','剧本原文依据','text'],['purpose','本镜叙事任务','text'],['action','可见动作与表演','text'],['characters','画面人物（顿号分隔）','names'],['creative_notes','表达细化与待确认项','text']]],
  ['镜头与空间', [['shot_size','景别','short'],['camera_angle','机位 / 角度','short'],['camera_motion','镜头运动','text'],['composition','画面构图','text'],['screen_direction','人物位置、视线与方向','text'],['lighting','照明','text'],['state_start','起始状态','text'],['state_end','结束状态','text'],['continuity_notes','连续性说明 / 例外理由','text']]],
  ['声音与节拍', [['dialogue_lines','对白（说话人｜原话，每行一句）','lines'],['dialogue','旧版台词补充','text'],['sound','环境声、音效与音乐意图','text'],['action_beats','动作节拍（秒｜动作，每行一项；秒可留空）','beats']]],
  ['静态帧与运动意图', [['frame_prompts.first','首帧：动作开始的瞬间','text'],['frame_prompts.key','关键帧（可选）','text'],['frame_prompts.last','尾帧（可选）','text'],['image_prompt','静态主画面候选（可选）','text'],['video_prompt','视频动作与镜头运动意图','text']]]
];
function fieldValue(shot,key) { return key.split('.').reduce((v,k)=>v?.[k],shot); }
function setField(shot,key,value) { const keys=key.split('.'); if(keys.length===2)shot[keys[0]][keys[1]]=value;else shot[key]=value; }
function parseLines(value,type) {
  return value.split('\n').filter(line=>line.trim()).map(line=>{
    const i=line.indexOf('｜')>=0?line.indexOf('｜'):line.indexOf('|');
    if(i<0)throw new Error('每行请使用“｜”分开两部分。');
    const left=line.slice(0,i).trim(),right=line.slice(i+1).trim();
    if(!right)throw new Error('内容不能为空。');
    if(type==='lines') { if(!left)throw new Error('请填写说话人，未知可写待确认。'); return {speaker:left,text:right}; }
    const seconds=left===''?null:Number(left);
    if(seconds!==null&&(!Number.isFinite(seconds)||seconds<=0||seconds>600))throw new Error('节拍时长应大于0且不超过600秒。');
    return {description:right,duration_ms:seconds===null?null:Math.round(seconds*1000)};
  });
}
function parseField(value,type) {
  if(type==='seconds') { const n=Number(value);if(!Number.isFinite(n)||n<.001||n>600||Math.abs(n*1000-Math.round(n*1000))>1e-6)throw new Error('请填写0.001至600秒之间、最多三位小数的时长。');return Math.round(n*1000); }
  if(type==='names')return value.split(/[、,，\n]/).map(x=>x.trim()).filter(Boolean);
  if(type==='lines'||type==='beats')return parseLines(value,type);
  return value;
}
function validateAllShots() {
  // 恢复后未打开的镜头也有原始编辑值；先逐镜重解析，不能只校验当前DOM。
  for(let index=0;index<draft.shots.length;index++) {
    const shot=draft.shots[index], raw=rawFields.get(shot.key)||{};
    for(const [,fields] of sections)for(const [key,,type] of fields) {
      if(!Object.hasOwn(raw,key))continue;
      try { setField(shot,key,parseField(raw[key],type)); }
      catch(e) {
        selected=index;renderShots();renderEditor();availability();
        const input=$('edit-'+key.replaceAll('.','-'));
        input.closest('details').open=true;input.setCustomValidity(e.message);input.reportValidity();
        return false;
      }
    }
  }
  const invalid=[...$('shot-form').elements].find(input=>!input.validity.valid);
  if(invalid)invalid.closest('details').open=true;
  return $('shot-form').reportValidity();
}
function renderEditor() {
  window.StoryboardMedia?.render();
  const shot=draft.shots[selected]; $('editor-heading').textContent=`镜头 ${String(selected+1).padStart(2,'0')} · ${shot.key}`;
  $('shot-fields').replaceChildren();
  for(const [title,fields] of sections) {
    const group=node('details',undefined,'field-section');group.open=title==='叙事与表演';group.append(node('summary',title));const grid=node('div',undefined,'field-grid');group.append(grid);
    for(const [key,label,type] of fields) {
      const box=node('div',undefined,type==='short'||type==='seconds'||type==='scene'?'':'field-wide');
      const id='edit-'+key.replaceAll('.','-'); const caption=node('label',label); caption.htmlFor=id;
      const input=node(type==='scene'?'select':type==='short'||type==='seconds'?'input':'textarea'); input.id=id;
      let value=fieldValue(shot,key);
      if(type==='scene')for(const scene of draft.scenes) { const option=node('option',scene.title);option.value=scene.key;input.append(option); }
      if(type==='seconds') { input.type='number';input.min='.001';input.max='600';input.step='.001';input.required=true;value=value/1000; }
      if(input.tagName==='TEXTAREA')input.rows=type==='text'?2:3;
      if(type==='names')value=(value||[]).join('、');
      if(type==='lines')value=(value||[]).map(x=>x.speaker+'｜'+x.text).join('\n');
      if(type==='beats')value=(value||[]).map(x=>(x.duration_ms===null?'':x.duration_ms/1000)+'｜'+x.description).join('\n');
      input.value=rawFields.get(shot.key)?.[key]??value??''; input.disabled=readonly();
      try{parseField(input.value,type);}catch(e){input.setCustomValidity(e.message);}
      input.oninput=()=>{
        rawFields.set(shot.key,{...rawFields.get(shot.key),[key]:input.value});
        markDirty(); input.setCustomValidity('');
        try {
          setField(shot,key,parseField(input.value,type));memory(scope(),{version:current.version,content:draft,raw:Object.fromEntries(rawFields)});renderShots();
        } catch(e) { input.setCustomValidity(e.message); }
      };
      box.append(caption,input); grid.append(box);
    }
    $('shot-fields').append(group);
  }
}
async function showReview() {
  const review=await api(boardUrl()+'/review?version='+current.version); $('review-issues').replaceChildren();
  for(const item of review.issues)$('review-issues').append(node('li',(item.shot_key||item.scene_key||'全文')+' · '+item.message));
  if(!review.issues.length)$('review-issues').append(node('li','当前程序规则未发现提醒项，仍需人工审阅。'));
}
async function refreshRuns() {
  if(!project)return;
  const runs=await api(base()+'/storyboard-runs'); $('runs').replaceChildren(); $('run-count').textContent=`已记录 ${runs.length} / 10 次分镜请求`;
  const pending=readMemory(pendingScope());
  if(pending&&runs.some(run=>run.idempotency_key===pending.idempotency_key&&run.status!=='running'))memory(pendingScope(),null);
  const labels={running:'执行中',succeeded:'已生成',failed:'失败',abandoned:'已标记中断'};
  for(const run of runs) {
    const box=node('article',undefined,'run-item'); box.append(node('strong',labels[run.status]+' · '+new Date(run.created_at).toLocaleString()),node('p',run.error||`${run.usage.total_tokens??'—'} tokens · 配置 V${run.manifest.request.profile.version}`));
    if(run.status==='running') {
      const button=node('button','标记中断（不取消外部请求）','secondary');button.type='button';button.onclick=()=>busy(async()=>{await api(base()+'/storyboard-runs/'+run.id+'/abandon',{});memory(pendingScope(),null);await refreshRuns();notice('已标记中断。旧请求即使返回也不会采用；如需重发，请先核对外部服务。');});box.append(button);
    }
    $('runs').append(box);
  }
  return runs;
}
$('project-form').onsubmit=e=>{e.preventDefault();busy(()=>loadProject($('project-id').value.trim()));};
$('config-form').onsubmit=e=>{e.preventDefault();busy(async()=>{
  const purpose=$('config-purpose').value;
  const profile=await api(prefix+'/model-profiles',{name:$('config-name').value,purpose,adapter:'openai_chat',base_url:$('config-url').value,model:$('config-model').value,api_key_env:$('config-env').value.trim(),reasoning_protocol:$('config-protocol').value});
  await profiles(profile.id+':'+profile.version,purpose);$('config-details').open=false;notice('模型配置已保存，尚未验证服务连接。');
});};
$('generate-form').onsubmit=e=>{e.preventDefault();busy(async()=>{
  if(!project)throw new Error('请先载入项目。'); if(!allowDiscard())return;
  const [profile_id,version]=$('profile').value.split(':');
  let payload={source_version:project.state.version,profile:{profile_id,version:Number(version)},target_shots:Number($('target-shots').value),aspect_ratio:$('aspect-ratio').value,visual_style:$('visual-style').value.trim(),instructions:$('instructions').value.trim(),reasoning_effort:$('effort').value||'default'};
  const pending=readMemory(pendingScope());
  if(pending) {
    payload=pending;
  } else payload={...payload,idempotency_key:crypto.randomUUID().replaceAll('-','')};
  memory(pendingScope(),payload); notice('正在规划分镜，请勿重复提交。关闭页面不会取消已发出的模型请求。');
  let result;
  try{result=await api(base()+'/storyboard-runs',payload);}catch(e){if([400,404,409,422].includes(e.status))memory(pendingScope(),null);throw e;}
  if(result.status!=='running')memory(pendingScope(),null);
  await refreshRuns();
  if(result.status==='succeeded') { memory(scope(),null);dirty=false;await refreshBoards();await openBoard(result.board.id);notice('分镜草案已保存。请逐镜核对、修改，再确认采用。'); }
  else if(result.status==='running')notice('该请求仍在执行，稍后刷新运行记录。');
  else error(result.error||'本次生成未完成，未创建分镜。');
});};
$('profile').onchange=availability;
$('refresh-runs').onclick=()=>busy(async()=>{await refreshRuns();notice('运行记录已刷新。已生成的方案可在分镜方案列表中打开。');await refreshBoards();if(!current&&boards.length)await openBoard(boards[boards.length-1].id);});
$('board-series').onchange=()=>{if(!allowDiscard()){$('board-series').value=current.id;return;}memory(scope(),null);dirty=false;busy(()=>openBoard($('board-series').value));};
$('history-version').onchange=()=>{if(!allowDiscard()){$('history-version').value=String(current.version);return;}memory(scope(),null);dirty=false;busy(()=>openBoard(current.id,Number($('history-version').value)));};
$('edit-title').oninput=()=>{draft.title=$('edit-title').value;markDirty();};
$('review-read').onchange=availability;
$('shot-form').onsubmit=e=>e.preventDefault();
$('save-board').onclick=()=>{if(!validateAllShots())return;busy(async()=>{
  const result=await api(boardUrl()+'/versions',{expected_version:current.version,content:draft});
  memory(scope(),null);dirty=false;await refreshBoards();await openBoard(result.id);notice('已保存新版本；上一版确认不会继承。');
});};
$('confirm-board').onclick=()=>busy(async()=>{
  if(dirty||!$('review-read').checked)throw new Error('请先保存修改并人工审阅当前版本。');
  const result=await api(boardUrl()+'/confirm',{expected_version:current.version});await openBoard(result.id);notice('当前分镜已确认，可以交给后续制作流程。');
});
$('add-shot').onclick=()=>{
  if(!$('shot-form').reportValidity())return;
  const shot=copy(draft.shots[selected]);shot.key='shot-'+crypto.randomUUID().slice(0,8);shot.purpose='请填写新镜头的叙事任务';
  draft.shots.splice(selected+1,0,shot);selected++;markDirty();renderShots();renderEditor();availability();
};
$('delete-shot').onclick=()=>{if(draft.shots.length<=1)return;draft.shots.splice(selected,1);selected=Math.min(selected,draft.shots.length-1);markDirty();renderShots();renderEditor();availability();};
for(const [id,offset] of [['move-up',-1],['move-down',1]])$(id).onclick=()=>{if(!$('shot-form').reportValidity())return;const next=selected+offset;if(next<0||next>=draft.shots.length)return;[draft.shots[next],draft.shots[selected]]=[draft.shots[selected],draft.shots[next]];selected=next;markDirty();renderShots();renderEditor();availability();};
$('download-board').onclick=()=>{if(!validateAllShots())return;const data={...current,content:draft,unsaved_changes:dirty};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=node('a');a.href=url;a.download=`framepilot-storyboard-v${current.version}${dirty?'-draft':''}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
const initial=new URL(location.href).searchParams.get('project')||last('framepilot:last-project');
if(initial){$('project-id').value=initial;busy(()=>loadProject(initial));}else busy(()=>profiles());

window.FramePilotWorkspace = {
 getContext(){return {stage:'storyboard',project_id:project?.id||new URL(location.href).searchParams.get('project')||null,storyboard_id:current?.id||null,shot_key:draft?.shots?.[selected]?.key||null,workspace_dirty:dirty,project_label:current?.content?.title||'分镜项目',version_label:current?'分镜 V'+current.version:'尚无分镜',save_label:dirty?'有未保存修改':'已保存',context_label:current?'分镜 V'+current.version+' · 第 '+(selected+1)+' 镜':'分镜规划'};},
 async refresh(result){if(dirty)throw Error('分镜有未保存修改，请先处理后重新读取。');if(!project||result.project_id!==project.id){await loadProject(result.project_id);return;}await refreshBoards();await refreshRuns();const id=result.storyboard_id||current?.id||boards.at(-1)?.id;if(id)await openBoard(id);},
 async selectReference(ref){if(ref.storyboard_id&&ref.storyboard_id!==current?.id){if(!allowDiscard())return;await openBoard(ref.storyboard_id);}const index=draft?.shots.findIndex(x=>x.key===ref.shot_key)??-1;if(index<0)return;selected=index;renderShots();renderEditor();availability();document.querySelector('.shot-editor').scrollIntoView({block:'start'});}
};

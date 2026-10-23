'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const project = params.get('project'), board = params.get('board');
  const base = `/api/production/projects/${encodeURIComponent(project || '')}/storyboards/${encodeURIComponent(board || '')}/editing`;
  const pendingKey = `framepilot:editing:export:${project}:${board}`;
  let data = null, draft = null, saved = '', busy = false, historical = false, pending = null, blocked = false;
  let localPending = null, previewExport = null;
  const copy = value => JSON.parse(JSON.stringify(value));
  const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  const button = (text, action, label) => { const n = el('button', text, 'secondary'); n.type = 'button'; if (label) n.setAttribute('aria-label', label); n.addEventListener('click', action); return n; };
  const dirty = () => !!draft && JSON.stringify(draft) !== saved;
  const writable = () => data && data.source_current && data.confirmed && !historical && !blocked;
  const safeMedia = value => { try { const url = new URL(value, location.origin); return value && url.origin === location.origin && /^https?:$/.test(url.protocol) ? url.href : null; } catch { return null; } };
  function showError(error) {
    $('error').hidden = false;
    $('error').textContent = error.message || String(error);
    $('error').focus();
  }
  function clearError() { $('error').hidden = true; $('error').textContent = ''; }
  async function api(path = '', body, extra = {}) {
    const response = await fetch(base + path, { method: body === undefined ? 'GET' : 'POST', ...(body === undefined ? {} : {headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}), ...extra });
    let result; try { result = await response.json(); } catch { result = {}; }
    if (!response.ok) {
      const detail = typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail || result.error || '请求失败');
      const error = new Error(response.status === 409 ? '版本已改变。请点击“重新读取”核对最新时间线，再重新编辑；本次没有覆盖保存。' : detail);
      error.status = response.status; throw error;
    }
    return result;
  }
  async function work(action) {
    if (busy) return;
    busy = true; clearError(); availability();
    try { await action(); } catch (error) { if (error.status === 409) blocked = true; showError(error); }
    finally { busy = false; availability(); }
  }
  function availability() {
    window.dispatchEvent(new Event('framepilot:studio-context'));
    const editable = writable() && !busy;
    document.querySelectorAll('#clips input,#clips button,#subtitles input,#subtitles textarea,#subtitles button,#audio-tracks input,#audio-tracks select,#audio-tracks button').forEach(n => n.disabled = !editable);
    $('preset').disabled = !editable;
    $('add-subtitle').disabled = !editable || draft.subtitles.length >= 100;
    $('add-audio').disabled = !editable || !data.audio.length || draft.audio_tracks.length >= 4;
    $('save').disabled = !editable || !draft.clips.length || !dirty();
    $('export').disabled = !editable || dirty() || !data.timeline || data.timeline.applicable === false || data.timeline.source_version !== data.source_version || !!pending;
    $('refresh').disabled = busy;
    $('history').disabled = busy || !data;
    $('new-from-selection').disabled = busy || !data || !data.source_current || !data.confirmed;
    $('upload').disabled = busy || !data || !data.source_current || !data.confirmed;
    $('audio-file').disabled = $('upload').disabled;
    $('retry-export').disabled = busy || !pending;
    $('upload-local').disabled = !editable || !!localPending;
    $('local-video-file').disabled = $('upload-local').disabled;
    $('retry-local').hidden = !localPending;
    $('retry-local').disabled = busy || !localPending;
    document.querySelectorAll('#local-clips button').forEach(n => n.disabled = !editable || n.dataset.applicable !== 'true' || draft.clips.length >= 30 || draft.clips.some(c=>c.run_id===n.dataset.asset));
    document.querySelectorAll('#exports button').forEach(n => n.disabled = busy);
    if (draft) {
      $('duration').replaceChildren(document.createTextNode((total() / 1000).toFixed(2) + ' '), el('small','秒'));
      $('clip-count').textContent = `${draft.clips.length} 镜`;
      $('save-state').textContent = historical ? '历史版本 · 只读' : blocked ? '版本冲突 · 需要重新读取' : dirty() ? '有未保存的编辑 · 请先保存' : data.timeline ? `时间线 V${data.timeline.version} · 已保存` : '尚无时间线';
    }
    $('pending-panel').hidden = !pending;
  }
  const total = () => draft.clips.reduce((sum, clip) => sum + clip.end_ms - clip.start_ms, 0);
  function changed() { availability(); }
  function numberField(parent, label, item, key, options = {}) {
    const wrap = el('label',label), input = el('input');
    input.type='number'; input.dataset.field=key; input.min=options.min ?? 0; input.step=options.step ?? '.01';
    if(options.max !== undefined)input.max=options.max;
    input.value=options.seconds ? item[key]/1000 : item[key];
    input.addEventListener('input',()=>{ item[key] = Number(input.value) * (options.seconds ? 1000 : 1); if(options.seconds)item[key]=Math.round(item[key]); changed(); });
    wrap.append(input);parent.append(wrap);return input;
  }
  function renderDraft() {
    $('preset').value=draft.preset;
    $('clips').replaceChildren();
    draft.clips.forEach((clip,index)=>{
      const source=data.selected_clips.find(x=>x.run_id===clip.run_id) || data.local_clips.find(x=>x.run_id===clip.run_id);
      const title=source?.shot_key || `素材 ${clip.run_id}`;
      const row=el('article',undefined,'clip'), head=el('div',undefined,'clip-head'), info=el('div',undefined,'clip-info');
      const heading=el('h3');heading.append(el('span',String(index+1).padStart(2,'0'),'clip-index'),document.createTextNode(title));info.append(heading,el('small',source ? `${source.source==='local_upload'?'本地导入 · ':''}素材时长 ${(source.duration_ms/1000).toFixed(2)} 秒` : '该素材来自已保存版本'));
      const actions=el('div',undefined,'row');
      if(index>0)actions.append(button('↑',()=>{[draft.clips[index-1],draft.clips[index]]=[draft.clips[index],draft.clips[index-1]];renderDraft();},`${title} 上移`));
      if(index<draft.clips.length-1)actions.append(button('↓',()=>{[draft.clips[index+1],draft.clips[index]]=[draft.clips[index],draft.clips[index+1]];renderDraft();},`${title} 下移`));
      actions.append(button('移除',()=>{draft.clips.splice(index,1);renderDraft();},`${title} 移除`));head.append(info,actions);row.append(head);
      const media=safeMedia(source?.media_url);if(media){const video=el('video');video.controls=true;video.preload='none';video.src=media;video.setAttribute('aria-label',`${title} 素材预览`);row.append(video);}
      const fields=el('div',undefined,'fields');numberField(fields,'起点（秒）',clip,'start_ms',{seconds:true,max:source?source.duration_ms/1000:undefined});numberField(fields,'终点（秒）',clip,'end_ms',{seconds:true,max:source?source.duration_ms/1000:undefined});numberField(fields,'原声增益',clip,'gain',{max:2});row.append(fields);$('clips').append(row);
    });
    if(!draft.clips.length)$('clips').append(el('p','暂无镜头。可从上方本地素材库加入片段，或返回分镜选用视频后重新建立时间线。','empty'));
    $('subtitles').replaceChildren();
    draft.subtitles.forEach((item,index)=>{
      const row=el('div',undefined,'subtitle'),fields=el('div',undefined,'fields');
      numberField(fields,'开始（秒）',item,'start_ms',{seconds:true});numberField(fields,'结束（秒）',item,'end_ms',{seconds:true});fields.append(button('移除',()=>{draft.subtitles.splice(index,1);renderDraft();},`移除字幕 ${index+1}`));
      const label=el('label',`字幕 ${index+1}`),text=el('textarea');text.rows=2;text.maxLength=200;text.dataset.field='text';text.value=item.text;text.addEventListener('input',()=>{item.text=text.value;changed();});label.append(text);row.append(fields,label);$('subtitles').append(row);
    });
    if(!draft.subtitles.length)$('subtitles').append(el('p','尚未添加字幕。','empty'));
    $('audio-tracks').replaceChildren();
    draft.audio_tracks.forEach((item,index)=>{
      const row=el('div',undefined,'audio-track'),fields=el('div',undefined,'fields'),label=el('label','音频素材'),select=el('select');select.dataset.field='asset_id';
      data.audio.forEach(asset=>{const option=el('option',asset.filename || asset.name || asset.id);option.value=asset.id;select.append(option);});
      if(!data.audio.some(a=>a.id===item.asset_id)){const option=el('option',`历史音频 ${item.asset_id}`);option.value=item.asset_id;select.append(option);}
      select.value=item.asset_id;select.addEventListener('change',()=>{item.asset_id=select.value;changed();});label.append(select);fields.append(label);
      numberField(fields,'进入时间（秒）',item,'offset_ms',{seconds:true});numberField(fields,'音量增益',item,'gain',{max:2});
      const loop=el('label',undefined,'check'),check=el('input');check.type='checkbox';check.checked=item.loop;check.addEventListener('change',()=>{item.loop=check.checked;changed();});loop.append(check,document.createTextNode('循环至片尾'));
      const actions=el('div',undefined,'row');actions.append(loop,button('移除音轨',()=>{draft.audio_tracks.splice(index,1);renderDraft();},`移除音轨 ${index+1}`));row.append(fields,actions);$('audio-tracks').append(row);
    });
    $('audio-state').textContent=`已上传 ${data.audio.length} 份音频 · 当前 ${draft.audio_tracks.length} / 4 条音轨`;
    renderLocalClips();availability();
  }
  function renderLocalClips() {
    $('local-clips').replaceChildren();
    for(const asset of data.local_clips) {
      const row=el('article',undefined,'clip'), title=asset.filename || asset.shot_key || asset.id;
      row.append(el('h3',title,'clip-info'),el('p',`本地导入 · 分镜 V${asset.version} · ${(asset.duration_ms/1000).toFixed(2)} 秒`,'hint'));
      const media=safeMedia(asset.media_url);
      if(media){const video=el('video');video.controls=true;video.preload='none';video.src=media;video.setAttribute('aria-label',`${title} 本地素材预览`);row.append(video);}
      const add=button('加入时间线',()=>{if(!writable()||draft.clips.length>=30||draft.clips.some(c=>c.run_id===asset.run_id))return;draft.clips.push({run_id:asset.run_id,start_ms:0,end_ms:asset.duration_ms,gain:1});renderDraft();},`${title} 加入时间线`);
      add.dataset.asset=asset.run_id;add.dataset.applicable=String(asset.applicable===true);row.append(add);
      if(!asset.applicable)row.append(el('p','历史素材 · 不能用于当前分镜新导出','hint'));
      $('local-clips').append(row);
    }
    if(!data.local_clips.length)$('local-clips').append(el('p','尚未上传本地视频。','empty'));
    $('local-state').textContent=`已保存 ${data.local_clips.length} 份本地素材 · 上传不自动加入时间线`;
  }
  function selectionDraft() { return {preset:'landscape',clips:data.selected_clips.map(x=>({run_id:x.run_id,start_ms:0,end_ms:x.duration_ms,gain:1})),subtitles:[],audio_tracks:[]}; }
  function validate() {
    if(!draft.clips.length || draft.clips.length>30)throw Error('请选择 1 至 30 个镜头。');
    draft.clips.forEach((c,i)=>{const source=data.selected_clips.find(x=>x.run_id===c.run_id)||data.local_clips.find(x=>x.run_id===c.run_id);if(!Number.isInteger(c.start_ms)||!Number.isInteger(c.end_ms)||c.start_ms<0||c.end_ms-c.start_ms<200||(source&&c.end_ms>source.duration_ms)||!Number.isFinite(c.gain)||c.gain<0||c.gain>2)throw Error(`镜头 ${i+1} 的裁切或增益无效；至少保留 0.2 秒，裁切不能超出素材。`);});
    if(total()>600000)throw Error('成片总时长不能超过 600 秒。');
    if(draft.subtitles.length>100||draft.subtitles.some(s=>!s.text.trim()||s.text.length>200||s.start_ms<0||s.end_ms<=s.start_ms||s.end_ms>total()))throw Error('请核对字幕：正文不能为空，时间范围必须在成片内。');
    if(draft.audio_tracks.length>4||draft.audio_tracks.some(a=>!a.asset_id||!Number.isFinite(a.offset_ms)||a.offset_ms<0||a.offset_ms>=total()||!Number.isFinite(a.gain)||a.gain<0||a.gain>2))throw Error('请核对音轨：进入时间必须在成片内，增益为 0 至 2。');
  }
  function renderExports() {
    $('exports').replaceChildren();
    const statuses={queued:'排队等待',running:'正在渲染',succeeded:'渲染成功',failed:'渲染失败',unknown:'结果未知'};
    const successful=(data.exports||[]).filter(x=>x.status==='succeeded');
    if(!successful.some(x=>x.id===previewExport))previewExport=successful[0]?.id||null;
    const current=successful.find(x=>x.id===previewExport);
    const preview=$('export-preview');if(preview){preview.replaceChildren();if(current){const path=`/exports/${encodeURIComponent(current.id)}`,media=safeMedia(current.media_url||base+path+'/media');preview.append(el('p',`正在预览：时间线 V${current.timeline_version??current.version??'?'} · ${current.id.slice(0,8)}`,'status'));if(media){const video=el('video');video.controls=true;video.preload='metadata';video.src=media;video.setAttribute('aria-label','导出成片预览');preview.append(video);}const link=el('a','下载当前成片');link.href=safeMedia(current.download_url)||base+path+'/download';link.download='';preview.append(link);}else preview.append(el('p','保存时间线并导出后，在这里预览成片。','empty'));}
    (data.exports||[]).forEach(record=>{
      const row=el('article',undefined,'export-item'),head=el('h3',`时间线 V${record.timeline_version??record.version??'?'} · ${statuses[record.status]||record.status}`);row.append(head);
      const identity=el('details'),identityText=el('small',record.id);identity.append(el('summary','任务编号'),identityText);row.append(identity);
      if(['queued','running'].includes(record.status))row.append(el('p',record.status==='queued'?'已排队，等待独立渲染进程。':'独立渲染进程正在处理。','hint'));
      if(record.error)row.append(el('p',typeof record.error==='string'?record.error:JSON.stringify(record.error),'hint'));
      if(record.status==='unknown')row.append(el('p','结果未知，请核对已有文件；不会自动重新渲染。','hint'));
      const path=`/exports/${encodeURIComponent(record.id)}`;
      if(['running','queued'].includes(record.status))row.append(button('标记结果未知',()=>work(async()=>{await api(path+'/abandon',{});await load(false);})));
      if(record.status==='succeeded'){
        const choose=button(record.id===previewExport?'正在预览':'预览此版本',()=>{previewExport=record.id;renderExports();$('export-preview')?.scrollIntoView({block:'start'});});choose.setAttribute('aria-pressed',String(record.id===previewExport));row.append(choose);
        const accepted=record.acceptance||record.accepted_at||record.accepted;
        row.append(el('p',accepted?'已人工验收':'未人工验收 · 请播放检查画面、声音与字幕。','status'));
        if(!accepted){const label=el('label',`验收时间线 V${record.timeline_version??record.version??'?'} · ${record.id.slice(0,8)}`),text=el('textarea');text.rows=2;text.maxLength=2000;label.append(text);row.append(label,button('记录人工验收',()=>work(async()=>{if(previewExport!==record.id)throw Error('请先预览此版本，再记录对应成片的人工验收。');await api(path+'/accept',{comment:text.value.trim()});await load(false);})));}
      }
      $('exports').append(row);
    });
    if(!data.exports?.length)$('exports').append(el('p','还没有导出记录。','empty'));
  }
  async function load(replaceDraft=true) {
    const result=await api();
    if(!replaceDraft && data && result.timeline?.version !== data.timeline?.version) {
      blocked=true;
      showError(Error('时间线已在其他页面更新。当前编辑内容仍保留，请点击“重新读取”核对新版本后再保存或导出。'));
    }
    data={...result,audio:result.audio||[],selected_clips:result.selected_clips||[],local_clips:result.local_clips||[],versions:result.versions||[],exports:result.exports||[]};
    $('source-state').textContent=!data.source_current?'上游来源已变化 · 请返回分镜重新确认。':!data.confirmed?'分镜尚未确认 · 请先完成确认。':`分镜 V${data.source_version} · 已确认`;
    $('message').textContent=data.source_current&&data.confirmed?'选用分镜视频或加入本地素材。先整理节奏与声音，再保存并导出。':'当前来源不能用于新导出；已有记录仍可回看。';
    if(replaceDraft){blocked=false;historical=false;draft=data.timeline?copy(data.timeline.content):selectionDraft();saved=data.timeline?JSON.stringify(draft):'';$('history').value='latest';renderDraft();}
    const choice=$('history').value;$('history').replaceChildren();const latest=el('option','最新时间线');latest.value='latest';$('history').append(latest);
    data.versions.forEach(version=>{const option=el('option',`V${version.version} · 分镜 V${version.source_version}`);option.value=String(version.version);$('history').append(option);});$('history').value=choice||'latest';
    renderExports();availability();
  }
  async function submitPending() {
    if(!pending)return;
    let result;
    try { result=await api('/exports',pending); }
    catch(error) {
      if([400,404,409,413,422].includes(error.status)){localStorage.removeItem(pendingKey);pending=null;}
      throw error;
    }
    localStorage.removeItem(pendingKey);pending=null;
    await load(false);
    $('message').textContent=`导出 ${result.id || ''} 已提交。等待独立渲染进程处理。`;
  }
  $('save').addEventListener('click',()=>work(async()=>{validate();const result=await api('/timeline',{expected_version:data.timeline?.version||0,source_version:data.source_version,content:copy(draft)});data.timeline=result;saved=JSON.stringify(draft);await load(false);$('message').textContent=`时间线 V${result.version} 已保存，可以提交成片导出。`;}));
  $('export').addEventListener('click',()=>work(async()=>{validate();if(dirty()||!data.timeline||historical||!writable())throw Error('请先保存当前且适用的时间线。');pending={expected_version:data.timeline.version,idempotency_key:crypto.randomUUID()};localStorage.setItem(pendingKey,JSON.stringify(pending));await submitPending();}));
  $('retry-export').addEventListener('click',()=>work(submitPending));
  $('refresh').addEventListener('click',()=>{if(dirty()&&!confirm('重新读取会替换尚未保存的编辑。继续吗？'))return;work(()=>load());});
  $('preset').addEventListener('change',()=>{draft.preset=$('preset').value;changed();});
  $('add-subtitle').addEventListener('click',()=>{draft.subtitles.push({start_ms:0,end_ms:Math.min(total(),2000),text:''});renderDraft();});
  $('add-audio').addEventListener('click',()=>{draft.audio_tracks.push({asset_id:data.audio[0].id,offset_ms:0,gain:1,loop:false});renderDraft();});
  $('new-from-selection').addEventListener('click',()=>{if(dirty()&&!confirm('将替换尚未保存的编辑。继续吗？'))return;historical=false;draft=selectionDraft();saved=data.timeline?JSON.stringify(data.timeline.content):'';$('history').value='latest';$('history-state').textContent='已从当前选片重新建立，请保存新版本。';renderDraft();});
  $('history').addEventListener('change',()=>{
    const version=$('history').value;
    if(dirty()&&!confirm('查看版本会替换尚未保存的编辑。继续吗？')){$('history').value='latest';return;}
    work(async()=>{if(version==='latest'){historical=false;draft=data.timeline?copy(data.timeline.content):selectionDraft();saved=data.timeline?JSON.stringify(draft):'';}
      else{let timeline=data.versions.find(v=>String(v.version)===version);if(!timeline?.content)timeline=await api('/timeline?version='+encodeURIComponent(version));historical=true;draft=copy(timeline.content);saved=JSON.stringify(draft);}
      $('history-state').textContent=historical?'历史版本只读。选择最新时间线继续编辑。':'每次保存都会保留独立版本。';renderDraft();});
  });
  $('upload-form').addEventListener('submit',event=>{event.preventDefault();work(async()=>{const file=$('audio-file').files[0];if(!file||!/\.wav$/i.test(file.name)||file.size>20*1024*1024)throw Error('请选择不超过 20 MiB 的 WAV 文件。');const asset=await api('/audio',undefined,{method:'POST',headers:{'Content-Type':'audio/wav','X-Filename':encodeURIComponent(file.name)},body:file});data.audio.push(asset);$('audio-file').value='';renderDraft();$('message').textContent='音频已上传。点击“添加音轨”将它放入时间线。';});});
  async function submitLocal() {
    const attempt=localPending;
    if(!attempt)return;
    let asset;
    try {
      asset=await api('/local-clips',undefined,{method:'POST',headers:{'Content-Type':attempt.mime,'X-Filename':encodeURIComponent(attempt.file.name),'X-Expected-Version':String(attempt.version),'X-Idempotency-Key':attempt.key},body:attempt.file});
      if(!asset.id||!asset.run_id||!Number.isInteger(asset.duration_ms))throw Error('上传结果尚未确认，请用原文件恢复上传。');
    } catch(error) {if([400,404,409,413,422].includes(error.status))localPending=null;throw error;}
    data.local_clips=data.local_clips.filter(x=>x.id!==asset.id);data.local_clips.push(asset);
    localPending=null;$('local-video-file').value='';renderDraft();
    $('message').textContent='本地视频已保存。请先预览，再明确加入时间线。';
  }
  $('local-upload-form').addEventListener('submit',event=>{event.preventDefault();work(async()=>{
    if(!writable())throw Error('请重新读取当前已确认分镜后上传。');
    const file=$('local-video-file').files[0];
    if(!file||!file.size||! /\.(mp4|webm)$/i.test(file.name)||file.size>256*1024*1024)throw Error('请选择不超过 256 MiB 的 MP4 或 WebM 文件。');
    localPending={file,version:data.source_version,key:crypto.randomUUID(),mime:/\.webm$/i.test(file.name)?'video/webm':'video/mp4'};
    await submitLocal();
  });});
  $('retry-local').addEventListener('click',()=>work(submitLocal));
  window.addEventListener('beforeunload',event=>{if(dirty()||localPending){event.preventDefault();event.returnValue='';}});
  window.FramePilotWorkspace = {
    getContext(){return {stage:'editing',project_id:project,storyboard_id:board,workspace_dirty:dirty(),project_label:'后期项目',version_label:data?.timeline?'时间线 V'+data.timeline.version:'尚无时间线',save_label:dirty()?'有未保存修改':'已保存',context_label:data?.timeline?'时间线 V'+data.timeline.version:'后期制作'};},
    async refresh(){if(dirty())throw Error('时间线有未保存修改，请先处理后重新读取。');await load();}
  };
  availability();
  $('identity').textContent=project&&board?`项目 ${project} / 分镜 ${board}`:'缺少项目或分镜编号';
  if(project&&board){$('back').href=`/storyboard?project=${encodeURIComponent(project)}&board=${encodeURIComponent(board)}`;try{const stored=JSON.parse(localStorage.getItem(pendingKey)||'null');if(stored&&Number.isInteger(stored.expected_version)&&typeof stored.idempotency_key==='string')pending=stored;}catch{showError(Error('无法读取上一次导出请求；请检查浏览器本地存储。'));}work(()=>load());}
  else{showError(Error('请从分镜工作台进入后期，或在地址中提供 project 和 board。'));$('refresh').disabled=true;}
})();

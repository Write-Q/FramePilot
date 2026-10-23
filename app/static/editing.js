'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const project = params.get('project'), board = params.get('board');
  const base = `/api/production/projects/${encodeURIComponent(project || '')}/storyboards/${encodeURIComponent(board || '')}/editing`;
  const pendingKey = `framepilot:editing:export:${project}:${board}`;
  let data = null, draft = null, saved = '', busy = false, historical = false, pending = null, blocked = false;
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
      const source=data.selected_clips.find(x=>x.run_id===clip.run_id);
      const title=source?.shot_key || `素材 ${clip.run_id}`;
      const row=el('article',undefined,'clip'), head=el('div',undefined,'clip-head'), info=el('div',undefined,'clip-info');
      const heading=el('h3');heading.append(el('span',String(index+1).padStart(2,'0'),'clip-index'),document.createTextNode(title));info.append(heading,el('small',source ? `素材时长 ${(source.duration_ms/1000).toFixed(2)} 秒` : '该素材来自已保存版本'));
      const actions=el('div',undefined,'row');
      if(index>0)actions.append(button('↑',()=>{[draft.clips[index-1],draft.clips[index]]=[draft.clips[index],draft.clips[index-1]];renderDraft();},`${title} 上移`));
      if(index<draft.clips.length-1)actions.append(button('↓',()=>{[draft.clips[index+1],draft.clips[index]]=[draft.clips[index],draft.clips[index+1]];renderDraft();},`${title} 下移`));
      actions.append(button('移除',()=>{draft.clips.splice(index,1);renderDraft();},`${title} 移除`));head.append(info,actions);row.append(head);
      const media=safeMedia(source?.media_url);if(media){const video=el('video');video.controls=true;video.preload='none';video.src=media;video.setAttribute('aria-label',`${title} 素材预览`);row.append(video);}
      const fields=el('div',undefined,'fields');numberField(fields,'起点（秒）',clip,'start_ms',{seconds:true,max:source?source.duration_ms/1000:undefined});numberField(fields,'终点（秒）',clip,'end_ms',{seconds:true,max:source?source.duration_ms/1000:undefined});numberField(fields,'原声增益',clip,'gain',{max:2});row.append(fields);$('clips').append(row);
    });
    if(!draft.clips.length)$('clips').append(el('p','暂无镜头。请返回分镜选用成功视频，再从当前选片建立时间线。','empty'));
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
    availability();
  }
  function selectionDraft() { return {preset:'landscape',clips:data.selected_clips.map(x=>({run_id:x.run_id,start_ms:0,end_ms:x.duration_ms,gain:1})),subtitles:[],audio_tracks:[]}; }
  function validate() {
    if(!draft.clips.length || draft.clips.length>30)throw Error('请选择 1 至 30 个镜头。');
    draft.clips.forEach((c,i)=>{const source=data.selected_clips.find(x=>x.run_id===c.run_id);if(!Number.isInteger(c.start_ms)||!Number.isInteger(c.end_ms)||c.start_ms<0||c.end_ms-c.start_ms<200||(source&&c.end_ms>source.duration_ms)||!Number.isFinite(c.gain)||c.gain<0||c.gain>2)throw Error(`镜头 ${i+1} 的裁切或增益无效；至少保留 0.2 秒，裁切不能超出素材。`);});
    if(total()>600000)throw Error('成片总时长不能超过 600 秒。');
    if(draft.subtitles.length>100||draft.subtitles.some(s=>!s.text.trim()||s.text.length>200||s.start_ms<0||s.end_ms<=s.start_ms||s.end_ms>total()))throw Error('请核对字幕：正文不能为空，时间范围必须在成片内。');
    if(draft.audio_tracks.length>4||draft.audio_tracks.some(a=>!a.asset_id||!Number.isFinite(a.offset_ms)||a.offset_ms<0||a.offset_ms>=total()||!Number.isFinite(a.gain)||a.gain<0||a.gain>2))throw Error('请核对音轨：进入时间必须在成片内，增益为 0 至 2。');
  }
  function renderExports() {
    $('exports').replaceChildren();
    const statuses={queued:'排队等待',running:'正在渲染',succeeded:'渲染成功',failed:'渲染失败',unknown:'结果未知'};
    (data.exports||[]).forEach(record=>{
      const row=el('article',undefined,'export-item'),head=el('h3',`时间线 V${record.timeline_version ?? record.version ?? '?'} · ${record.id}`);head.append(el('span',statuses[record.status] || record.status,'stage'));row.append(head);
      if(record.status==='queued')row.append(el('p','已排队，等待独立渲染进程处理。请使用“重新读取”查看状态。','hint'));
      if(record.status==='running')row.append(el('p','独立渲染进程正在处理。页面不会自行启动或重新执行渲染。','hint'));
      if(record.error)row.append(el('p',typeof record.error==='string'?record.error:JSON.stringify(record.error),'hint'));
      if(record.status==='unknown')row.append(el('p','上次渲染结果未知，不会自动重新渲染。核对后可从已保存时间线另行提交。','hint'));
      const path=`/exports/${encodeURIComponent(record.id)}`;
      if(['running','queued'].includes(record.status))row.append(button('标记结果未知',()=>work(async()=>{await api(path+'/abandon',{});await load(false);})));
      if(record.status==='succeeded'){
        const media=safeMedia(record.media_url || base+path+'/media');
        if(media){const video=el('video');video.controls=true;video.preload='metadata';video.src=media;video.setAttribute('aria-label','导出成片预览');row.append(video);const link=el('a','下载成片');link.href=safeMedia(record.download_url)||base+path+'/download';link.download='';row.append(link);}
        const accepted=record.acceptance || record.accepted_at || record.accepted;
        row.append(el('p',accepted?'已人工验收':'未人工验收 · 请播放检查画面、声音与字幕。','status'));
        if(!accepted){const label=el('label','成片验收意见'),text=el('textarea');text.rows=2;text.maxLength=2000;label.append(text);row.append(label,button('记录人工验收',()=>work(async()=>{await api(path+'/accept',{comment:text.value.trim()});await load(false);})));}
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
    data={...result,audio:result.audio||[],selected_clips:result.selected_clips||[],versions:result.versions||[],exports:result.exports||[]};
    $('source-state').textContent=!data.source_current?'上游来源已变化 · 请返回分镜重新确认。':!data.confirmed?'分镜尚未确认 · 请先完成确认。':`分镜 V${data.source_version} · 已确认`;
    $('message').textContent=data.source_current&&data.confirmed?'从已选用视频开始。先整理节奏与声音，再保存并导出。':'当前来源不能用于新导出；已有记录仍可回看。';
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
  window.addEventListener('beforeunload',event=>{if(dirty()){event.preventDefault();event.returnValue='';}});
  availability();
  $('identity').textContent=project&&board?`项目 ${project} / 分镜 ${board}`:'缺少项目或分镜编号';
  if(project&&board){$('back').href=`/storyboard?project=${encodeURIComponent(project)}&board=${encodeURIComponent(board)}`;try{const stored=JSON.parse(localStorage.getItem(pendingKey)||'null');if(stored&&Number.isInteger(stored.expected_version)&&typeof stored.idempotency_key==='string')pending=stored;}catch{showError(Error('无法读取上一次导出请求；请检查浏览器本地存储。'));}work(()=>load());}
  else{showError(Error('请从分镜工作台进入后期，或在地址中提供 project 和 board。'));$('refresh').disabled=true;}
})();

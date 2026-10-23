'use strict';
window.StoryboardVideo = (() => {
  let loadedFor='', generation=0;
  const pendingActions=new Map();
  const identity=()=>current?`${project?.id}:${current.id}:${current.version}`:'';
  const labels={queued:'等待生成服务处理',submitting:'正在提交生成请求',submitted:'已提交，等待结果',running:'正在生成',polling:'正在查询结果',succeeded:'已生成',failed:'生成失败',unknown:'结果未知',cancelled:'已取消'};
  const canSelect=()=>!!current&&current.confirmed&&!dirty&&!readonly()&&loadedFor===identity();
  function mediaUrl(value) {
    if(!value)return null;
    try {const url=new URL(value,location.origin);return url.origin===location.origin&&['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null;}catch{return null;}
  }
  function availability() {
    $('refresh-videos').disabled=working||!current;
    if(loadedFor!==identity()) {
      $('video-runs').replaceChildren();
      $('video-runs-status').textContent=current?'请刷新当前分镜的视频记录。':'载入分镜后可查看视频记录。';
    }
    for(const button of $('video-runs').querySelectorAll('button')) {
      const mutation=['select','inspect','note','finding-add','finding-remove'].includes(button.dataset.videoAction);
      const pending=pendingActions.has(button.dataset.pendingKey);
      button.disabled=working||(mutation&&(!canSelect()||button.dataset.selectable!=='true'))||(pending&&['finding-add','finding-remove'].includes(button.dataset.videoAction));
      if(button.dataset.videoAction==='inspect')button.textContent=pending?'恢复上次检查请求':'检查视频';
      if(button.dataset.videoAction==='note')button.textContent=pending?'恢复上次人工结论':'保存人工结论';
    }
    for(const input of $('video-runs').querySelectorAll('[data-video-field]'))input.disabled=working||!canSelect()||input.dataset.selectable!=='true'||pendingActions.has(input.dataset.pendingKey);
  }
  const seconds=value=>Number.isFinite(value)?(value/1000).toFixed(3):'未知';
  const contentLabels={pending:'待人工审核',reviewed:'人工已审阅',needs_revision:'需修改'};
  const severityLabels={low:'低',medium:'中',high:'高'};
  const warningLabels={duration_mismatch:'实际时长与计划不一致，请人工核对。',aspect_ratio_mismatch:'实际画幅与计划不一致，请人工核对。'};
  async function submitOnce(key,endpoint,payload) {
    if(!pendingActions.has(key))pendingActions.set(key,payload);
    try {const result=await api(endpoint,pendingActions.get(key));pendingActions.delete(key);return result;}
    catch(error){if(error.status>=400&&error.status<500)pendingActions.delete(key);throw error;}
  }
  function inspectionPanel(article,video,run,endpoint,loadedIdentity) {
    const eligible=!!run.applicable&&run.version===current.version;
    const inspectKey=loadedIdentity+':'+run.id+':inspect';
    const panel=node('section',undefined,'video-inspection');
    const toolbar=node('div',undefined,'row'), status=node('p',pendingActions.has(inspectKey)?'上次检查响应未确认，请恢复原请求。':'按需抽帧并记录人工审核，不调用视觉模型。','hint');
    status.setAttribute('role','status');
    const reportsBox=node('div');
    const sameContext=()=>loadedIdentity===identity()&&article.isConnected;
    function assertContext(mutation=false) {
      if(!sameContext())throw new Error('分镜已切换，请刷新后操作。');
      if(mutation&&(!canSelect()||!eligible))throw new Error('请保存并确认当前有效分镜后检查或记录结论。');
    }
    function button(label,action,selectable=eligible,pendingKey='') {
      const element=node('button',label,'secondary');element.type='button';element.dataset.videoAction=action;element.dataset.selectable=String(selectable);element.dataset.pendingKey=pendingKey;return element;
    }
    async function loadReports() {
      assertContext();
      const value=await api(endpoint+'/inspections');
      if(!sameContext())return;
      reportsBox.replaceChildren();
      const reports=value.reports||[];
      status.textContent=reports.length?`共 ${reports.length} 份检查记录；请结合完整播放核对。`:'尚无检查记录。点击“检查视频”获取采样证据。';
      for(const report of reports)renderReport(report);
      availability();
    }
    function renderReport(report) {
      const editable=eligible&&report.applicable===true&&report.version===current.version;
      const section=node('section',undefined,'video-inspection-report');
      section.dataset.reportId=report.id;section.dataset.contentStatus=report.content_status||'pending';
      section.append(node('h4',`视频检查 · V${report.version} · ${contentLabels[report.content_status]||'待人工审核'}`));
      if(!editable)section.append(node('p','历史或已失效报告，只读保留。','hint'));
      const technical=report.technical||{},actual=technical.actual||{},planned=technical.planned||{},parts=[];
      if(Number.isFinite(actual.width)&&Number.isFinite(actual.height))parts.push(`${actual.width} × ${actual.height}`);
      if(Number.isFinite(actual.duration_ms))parts.push(`实际 ${seconds(actual.duration_ms)} 秒`);
      if(Number.isFinite(planned.duration_ms))parts.push(`计划 ${seconds(planned.duration_ms)} 秒`);
      if(planned.aspect_ratio)parts.push(`计划画幅 ${planned.aspect_ratio}`);
      if(parts.length)section.append(node('p',parts.join(' · '),'hint'));
      for(const warning of technical.warnings||[])section.append(node('p',warningLabels[warning]||`技术提示：${warning}`,'hint'));
      section.append(node('p','抽帧是稀疏证据，不能证明完整视频均无问题。请完整播放，人工核对动作、人物身份、口型与声音。技术检查不代表内容审核通过。','hint'));
      const frames=node('div',undefined,'video-inspection-frames');
      for(const frame of report.frames||[]) {
        const url=mediaUrl(frame.url);if(!url||!Number.isFinite(frame.at_ms)||frame.at_ms<0)continue;
        const jump=button('', 'seek',true);jump.setAttribute('aria-label',`定位视频至 ${seconds(frame.at_ms)} 秒`);
        const image=node('img');image.src=url;image.loading='lazy';image.alt=`采样画面 ${seconds(frame.at_ms)} 秒`;
        jump.append(image,node('span',`${seconds(frame.at_ms)} 秒`));
        jump.onclick=()=>{try{assertContext();video.currentTime=frame.at_ms/1000;}catch(error){status.textContent=error.message;}};
        frames.append(jump);
      }
      section.append(frames);
      for(const note of report.notes||[]) {
        const record=node('div',undefined,'video-inspection-note');
        record.append(node('strong',`人工记录 · ${contentLabels[note.decision]||'待人工审核'}`));
        if(note.comment)record.append(node('p',note.comment));
        for(const finding of note.findings||[])record.append(node('p',`${seconds(finding.start_ms)}–${seconds(finding.end_ms)} 秒 · ${severityLabels[finding.severity]||finding.severity||'中'} · ${finding.description}`));
        section.append(record);
      }
      if(editable)renderNoteForm(section,report,actual);
      reportsBox.append(section);
    }
    function renderNoteForm(section,report,actual) {
      const noteKey=loadedIdentity+':'+run.id+':note:'+report.id, pending=pendingActions.get(noteKey);
      const form=node('form',undefined,'video-inspection-form'), findings=node('div',undefined,'video-inspection-findings');
      const decision=node('select');decision.required=true;
      for(const [value,label] of [['','请选择人工结论'],['reviewed','人工已审阅'],['needs_revision','需修改']]){const option=node('option',label);option.value=value;decision.append(option);}
      const comment=node('textarea');comment.rows=3;comment.maxLength=2000;
      function field(label,input) {
        const wrapper=node('label',label);input.setAttribute('aria-label',label);input.dataset.videoField='true';input.dataset.selectable='true';input.dataset.pendingKey=noteKey;wrapper.append(input);return wrapper;
      }
      function addFinding(value={}) {
        const row=node('div',undefined,'video-inspection-finding'), range=node('div',undefined,'pair');
        const start=node('input'),end=node('input'),description=node('input'),severity=node('select');
        for(const input of [start,end]){input.type='number';input.min='0';input.step='0.001';input.required=true;if(Number.isFinite(actual.duration_ms))input.max=String(actual.duration_ms/1000);}
        description.required=true;description.maxLength=2000;
        start.value=Number.isFinite(value.start_ms)?String(value.start_ms/1000):'';end.value=Number.isFinite(value.end_ms)?String(value.end_ms/1000):'';description.value=value.description||'';
        for(const [value,label] of Object.entries(severityLabels)){const option=node('option',label);option.value=value;severity.append(option);}severity.value=value.severity||'medium';
        range.append(field('开始（秒）',start),field('结束（秒）',end));
        row.append(range,field('问题描述',description),field('严重程度',severity));
        const remove=button('移除这条发现','finding-remove',true,noteKey);remove.onclick=()=>{row.remove();availability();};row.append(remove);
        row.readFinding=()=>{const start_ms=Math.round(Number(start.value)*1000),end_ms=Math.round(Number(end.value)*1000);if(end_ms<=start_ms)throw new Error('发现的结束时间必须晚于开始时间。');if(!description.value.trim())throw new Error('请填写问题描述。');return {start_ms,end_ms,severity:severity.value,description:description.value.trim()};};
        findings.append(row);availability();
      }
      const add=button('添加时间区间发现','finding-add',true,noteKey);add.onclick=()=>addFinding();
      const save=button('保存人工结论','note',true,noteKey);save.type='submit';
      form.append(field('人工结论',decision),node('p','只有在人工核对后才选择结论；保存不会自动选用视频。','hint'),findings,add,field('审核补充说明',comment),save);
      if(pending){decision.value=pending.decision;comment.value=pending.comment;for(const finding of pending.findings)addFinding(finding);}
      form.onsubmit=event=>{
        event.preventDefault();
        if(!pendingActions.has(noteKey)&&!form.reportValidity())return;
        busy(async()=>{
          assertContext(true);
          if(!report.applicable||report.version!==current.version)throw new Error('此检查报告已失效，只能查看。');
          const payload=pendingActions.get(noteKey)||{expected_version:current.version,idempotency_key:crypto.randomUUID(),decision:decision.value,findings:Array.from(findings.children,row=>row.readFinding()),comment:comment.value.trim()};
          if(!['reviewed','needs_revision'].includes(payload.decision))throw new Error('请选择人工结论。');
          try {await submitOnce(noteKey,endpoint+'/inspections/'+encodeURIComponent(report.id)+'/notes',payload);if(sameContext())await loadReports();}
          catch(error){if(sameContext())status.textContent=pendingActions.has(noteKey)?'人工结论响应未确认，请恢复原请求：'+error.message:'人工结论未完成，请核对后重试：'+error.message;throw error;}
        });
      };
      section.append(form);
    }
    const inspect=button('检查视频','inspect',eligible,inspectKey), history=button('查看审核记录','inspection-history',true);
    inspect.onclick=()=>busy(async()=>{
      assertContext(true);status.textContent='正在抽取视频证据，请稍候…';
      try {await submitOnce(inspectKey,endpoint+'/inspections',{idempotency_key:crypto.randomUUID(),count:8});if(sameContext())await loadReports();}
      catch(error){if(sameContext())status.textContent=pendingActions.has(inspectKey)?'检查响应未确认，请恢复原请求：'+error.message:'检查未完成，请核对后重试：'+error.message;throw error;}
    });
    history.onclick=()=>busy(async()=>{try{await loadReports();}catch(error){if(sameContext())status.textContent='读取审核记录失败，请重试：'+error.message;throw error;}});
    toolbar.append(inspect,history);panel.append(toolbar,status,reportsBox);article.append(panel);
  }
  function showRuns(runs) {
    $('video-runs').replaceChildren();
    $('video-runs-status').textContent=runs.length?`本方案共 ${runs.length} 条视频任务记录。`:'本方案尚无视频任务。';
    for(const run of runs) {
      const article=node('article',undefined,'run-item');
      article.dataset.videoRunId=run.id;
      article.append(node('strong',`${run.shot_key} · V${run.version}${run.version!==current.version?' · 历史版本':''} · ${labels[run.status]||run.status}`));
      const loadedIdentity=identity(), endpoint=boardUrl()+'/video-runs/'+encodeURIComponent(run.id);
      function action(label,suffix,selectable=true) {
        const button=node('button',label,'secondary');button.type='button';button.dataset.videoAction=suffix;button.dataset.selectable=String(selectable);
        button.onclick=()=>busy(async()=>{
          if(loadedIdentity!==identity())throw new Error('分镜已切换，请刷新后操作。');
          if(suffix==='select'&&(!canSelect()||!selectable))throw new Error('请保存并确认当前有效分镜后选用。');
          await api(endpoint+'/'+suffix,suffix==='select'?{expected_version:current.version}:{});await refresh();
        });article.append(button);
      }
      const url=run.status==='succeeded'?mediaUrl(run.media_url):null;
      if(url) {
        const video=node('video');video.controls=true;video.preload='metadata';video.playsInline=true;video.src=url;video.setAttribute('aria-label',`${run.shot_key} V${run.version} 视频候选`);
        article.append(video);
        const metadata=run.output?.metadata||{}, parts=[];
        if(Number.isFinite(metadata.width)&&Number.isFinite(metadata.height))parts.push(`${metadata.width} × ${metadata.height}`);
        if(Number.isFinite(metadata.duration_ms))parts.push(`实际 ${(metadata.duration_ms/1000).toFixed(2)} 秒`);
        if(Number.isFinite(run.duration_ms)) {
          parts.push(`计划 ${(run.duration_ms/1000).toFixed(2)} 秒`);
          if(Number.isFinite(metadata.duration_ms)){const delta=(metadata.duration_ms-run.duration_ms)/1000;parts.push(`相差 ${delta>0?'+':''}${delta.toFixed(2)} 秒`);}
        }
        if(parts.length)article.append(node('p',parts.join(' · '),'hint'));
        article.append(node('p','请播放并核对画面、动作与声音。文件可播放不代表内容审核通过。','hint'));
        action(run.selected?'已选用此视频':'选用此视频','select',!!run.applicable&&run.version===current.version&&!run.selected);
        inspectionPanel(article,video,run,endpoint,loadedIdentity);
      }
      if(run.selected)article.append(node('p',run.applicable?'已选用':'历史选用记录，当前不可采用','hint'));
      if(run.error)article.append(node('p',run.error,'hint'));
      if(run.status==='unknown')article.append(node('p','请核对服务端结果；不会自动重新提交。','hint'));
      if(run.status==='queued')action('取消排队','cancel');
      if(['submitting','submitted','polling'].includes(run.status)) {
        article.append(node('p','标记结果未知不会取消供应商的生成请求。','hint'));action('标记结果未知','abandon');
      }
      if(run.status==='polling'&&run.external_id) {
        article.append(node('p','恢复查询只检查原服务任务，不会重新提交生成。','hint'));action('恢复查询原任务','recover-poll');
      }
      if(run.external_id){const detail=node('details');detail.append(node('summary','服务任务编号'),node('p',run.external_id));article.append(detail);}
      $('video-runs').append(article);
    }
  }
  async function refresh() {
    const ticket=++generation, requested=identity();
    loadedFor='';$('video-runs').replaceChildren();
    $('video-service-status').textContent='正在读取视频服务状态…';
    $('video-runs-status').textContent=current?'正在读取视频任务记录…':'载入分镜后可查看视频记录。';
    const url=current?boardUrl()+'/video-runs?version='+current.version:null;
    const [service,history]=await Promise.allSettled([api(prefix+'/video-adapters'),url?api(url):Promise.resolve(null)]);
    if(ticket!==generation||requested!==identity())return;
    loadedFor=requested;
    if(service.status==='rejected')$('video-service-status').textContent='无法读取视频服务状态：'+service.reason.message;
    else {
      const state=service.value;
      $('video-service-status').textContent=!state.registered.length?'尚未接入视频服务。':!state.media_validator_configured?'已注册视频服务，输出校验尚未配置。':'已注册视频服务并配置输出校验。';
      if(state.registered.length&&!state.capabilities_verified)$('video-service-status').textContent+=' 服务能力尚未验证。';
    }
    if(history.status==='rejected')$('video-runs-status').textContent='无法读取视频任务记录：'+history.reason.message;
    else if(history.value)showRuns(history.value.runs||[]);
    availability();
  }
  $('refresh-videos').onclick=()=>busy(refresh);
  return {availability,refresh};
})();

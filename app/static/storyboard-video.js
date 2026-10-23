'use strict';
window.StoryboardVideo = (() => {
  let loadedFor='', generation=0;
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
    for(const button of $('video-runs').querySelectorAll('button'))button.disabled=working||(button.dataset.videoAction==='select'&&(!canSelect()||button.dataset.selectable!=='true'));
  }
  function showRuns(runs) {
    $('video-runs').replaceChildren();
    $('video-runs-status').textContent=runs.length?`本方案共 ${runs.length} 条视频任务记录。`:'本方案尚无视频任务。';
    for(const run of runs) {
      const article=node('article',undefined,'run-item');
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

'use strict';
window.StoryboardReview = (() => {
  let runs=[], loaded=false, selectedReport=null;
  const endpoint=()=>boardUrl()+'/review-runs';
  const pendingKey=()=>`framepilot:review-pending:${project?.id}:${current?.id}`;
  const labels={running:'执行中',succeeded:'已返回报告',failed:'失败',abandoned:'已标记中断'};
  const severity={high:'严重',medium:'一般',low:'轻微'};
  const reasons={board_changed:'分镜已更新',source_changed:'剧本已变化或未确认',context_changed:'创作卡或约束已变化'};

  function availability() {
    const pending=current&&readMemory(pendingKey());
    $('review-profile').disabled=working||!!pending;
    $('start-review').disabled=working||readonly()||dirty||!loaded||!$('review-profile').value||runs.some(r=>r.status==='running');
    $('start-review').textContent=pending?'恢复上次审核请求':'审核当前文字分镜';
    $('refresh-reviews').disabled=working||!current;
    if(pending) {
      const value=pending.profile.profile_id+':'+pending.profile.version;
      if(![...$('review-profile').options].some(o=>o.value===value)) {
        const option=node('option','上次审核的固定配置 · V'+pending.profile.version);option.value=value;$('review-profile').append(option);
      }
      $('review-profile').value=value;
    }
    ModelPicker.sync('review-profile','review-effort',{pending,disabled:working});
    if(dirty)$('model-review-status').textContent='有未保存修改：报告只对应已保存版本，请保存后重新审核。';
    else if(selectedReport) {
      const matching=selectedReport.storyboard_version_id===current?.version_id;
      const state=selectedReport.applicable&&matching?'对应当前已保存版本':'历史报告 / 已过期';
      $('model-review-status').textContent=`分镜 V${selectedReport.version} · ${state}${selectedReport.stale_reasons.length?' · '+selectedReport.stale_reasons.map(r=>reasons[r]||r).join('、'):''}。请人工判断；报告不代表审核通过。`;
    } else if(loaded)$('model-review-status').textContent=runs.some(r=>r.status==='running')?'审核请求执行中，请稍后刷新记录。':'当前尚无可用报告。审核不会自动发起。';
    for(const button of $('model-review-result').querySelectorAll('button'))button.disabled=working||dirty||selectedReport?.storyboard_version_id!==current?.version_id;
  }

  function setProfiles(items, selectId) {
    ModelPicker.setModels('review-profile','review-effort',items.filter(p=>p.config.purpose==='review'&&p.config.adapter==='openai_chat'),selectId);
    availability();
  }

  function showReport(run) {
    selectedReport=run;$('model-review-result').replaceChildren();
    if(!run){availability();return;}
    if(!run.report.issues.length)$('model-review-result').append(node('p','模型未报告问题。这不证明没有遗漏，也不替代人工审阅。','hint'));
    for(const issue of run.report.issues) {
      const article=node('article',undefined,'model-review-issue');
      article.append(node('strong',`${severity[issue.severity]} · ${issue.certainty==='needs_confirmation'?'待确认':'有引文支持，仍需核实判断'}`),
        node('p',issue.description),node('p','建议：'+issue.suggestion));
      for(const evidence of issue.evidence)article.append(node('blockquote',`${evidence.source} / ${evidence.key||'正文'} / ${evidence.field}：“${evidence.quote}”`));
      for(const key of issue.shot_keys) {
        const button=node('button','定位 '+key,'text-button');button.type='button';
        button.onclick=()=>{
          if(dirty||run.storyboard_version_id!==current.version_id||!$('shot-form').reportValidity())return;
          const index=draft.shots.findIndex(shot=>shot.key===key);if(index<0)return;
          selected=index;renderShots();renderEditor();window.availability();$('editor-heading').scrollIntoView({behavior:'smooth',block:'center'});
        };
        article.append(button);
      }
      $('model-review-result').append(article);
    }
    availability();
  }

  async function refresh() {
    if(!current)return;
    loaded=false;runs=[];showReport(null);$('model-review-runs').replaceChildren();
    try {
      runs=await api(endpoint());loaded=true;
      const pending=readMemory(pendingKey());
      if(pending&&runs.some(r=>r.idempotency_key===pending.idempotency_key&&r.status!=='running'))memory(pendingKey(),null);
      $('review-count').textContent=runs.length?`项目已记录 ${runs[0].used_runs} / 10 次独立文字审核（包括其他分镜方案）。`:'每项目累计最多 10 次独立文字审核，失败和中断也计入。';
      for(const run of runs) {
        const article=node('article',undefined,'run-item');
        article.append(node('strong',`分镜 V${run.version} · ${labels[run.status]} · ${new Date(run.created_at).toLocaleString()}`));
        if(run.error)article.append(node('p',run.error));
        if(run.report) {
          const button=node('button','查看此报告','secondary');button.type='button';button.onclick=()=>showReport(run);article.append(button);
        }
        if(run.status==='running') {
          const button=node('button','标记中断（不取消外部请求）','secondary');button.type='button';
          button.onclick=()=>busy(async()=>{await api(endpoint()+'/'+run.id+'/abandon',{});memory(pendingKey(),null);await refresh();});article.append(button);
        }
        const detail=node('details');detail.append(node('summary','固定版本、规则与来源'),node('pre',JSON.stringify({source_version_id:run.source_version_id,storyboard_version_id:run.storyboard_version_id,profile_id:run.profile_id,profile_version:run.profile_version,manifest:run.manifest},null,2)));article.append(detail);
        $('model-review-runs').append(article);
      }
      showReport(runs.find(r=>r.report&&r.storyboard_version_id===current.version_id)||runs.find(r=>r.report)||null);
    } catch(e) {
      $('model-review-status').textContent='审核记录暂时不可用：'+e.message;
    }
    availability();
  }

  $('review-profile').onchange=availability;
  $('refresh-reviews').onclick=()=>busy(async()=>{
    if(!dirty)await openBoard(current.id,current.version===current.current_version?undefined:current.version);
    else await refresh();
  });
  $('start-review').onclick=()=>busy(async()=>{
    if(dirty||readonly())throw new Error('请先保存当前分镜，再发起审核。');
    const url=endpoint(),key=pendingKey();
    const [profile_id,version]=$('review-profile').value.split(':');
    const request=readMemory(key)||{expected_version:current.version,profile:{profile_id,version:Number(version)},idempotency_key:crypto.randomUUID().replaceAll('-',''),reasoning_effort:$('review-effort').value||'default'};
    memory(key,request);$('model-review-status').textContent='正在单独审核已保存的文字分镜，请勿重复提交。';
    let result;
    try{result=await api(url,request);}catch(e){if([400,404,409,422].includes(e.status))memory(key,null);throw e;}
    if(result.status!=='running')memory(key,null);
    // 重新读取服务器版本，让其他窗口的改稿使旧报告立即显示过期。
    await openBoard(current.id);
    if(result.error)error(result.error);
  });
  return {availability,setProfiles,refresh};
})();

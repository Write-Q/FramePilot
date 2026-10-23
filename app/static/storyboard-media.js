'use strict';
window.StoryboardMedia = (() => {
  let runs=[], loadedFor='', context='';
  const roles={first:'首帧',key:'关键帧',last:'尾帧'};
  const labels={queued:'等待生成服务处理',running:'正在生成',succeeded:'已生成',failed:'生成失败',unknown:'结果未知',cancelled:'已取消'};
  const endpoint=()=>boardUrl()+'/media-runs';
  const identity=()=>current?`${project.id}:${current.id}:${current.version}`:'';
  const pendingKey=()=>`framepilot:media-pending:${project?.id}:${current?.id}`;
  const shot=()=>draft?.shots[selected];
  const editable=()=>!!current&&!readonly()&&!dirty&&current.confirmed;
  const promptKey=()=>`framepilot:frame-prompt:${identity()}:${shot()?.key}:${$('frame-role').value}`;
  function image(url,alt) {
    if(!url)return null;
    try {const parsed=new URL(url,location.origin);if(parsed.origin!==location.origin||!['http:','https:'].includes(parsed.protocol))return null;
      const img=node('img');img.src=parsed.href;img.alt=alt;img.loading='lazy';return img;
    }catch{return null;}
  }
  function setProfiles(items,selectId) {
    const select=$('image-profile'), previous=selectId||select.value;select.replaceChildren(node('option','选择图像模型'));select.firstChild.value='';
    for(const item of items.filter(p=>p.config.purpose==='image'&&p.config.adapter==='openai_images')) {
      const option=node('option',`${item.config.name||item.config.model} · V${item.version}`);option.value=item.id+':'+item.version;select.append(option);
    }
    if([...select.options].some(o=>o.value===previous))select.value=previous;
    else if(select.options.length===2)select.selectedIndex=1;
    availability();
  }
  function render() {
    const next=promptKey();
    if(context!==next){context=next;$('frame-prompt').value=readMemory(next)||'';$('image-size').value=({'16:9':'1536x864','9:16':'864x1536','1:1':'1024x1024'})[draft?.aspect_ratio]||'1536x864';$('video-input-preview').replaceChildren();}
    $('media-shot').textContent=shot()?`${shot().key} / ${roles[$('frame-role').value]}`:'先选择镜头';
    const candidates=$('media-candidates');candidates.replaceChildren();
    const relevant=loadedFor===identity()?runs.filter(r=>r.shot_key===shot()?.key&&r.frame_role===$('frame-role').value):[];
    if(!relevant.length)candidates.append(node('p','尚无图片候选。预览提示词后，生成这一镜的静态帧。','hint'));
    for(const run of relevant) {
      const card=node('article',undefined,'media-candidate');const matching=run.version===current?.version;
      const img=image(run.media_url,`${run.shot_key} ${roles[run.frame_role]}候选`);if(img)card.append(img);
      card.append(node('strong',`${labels[run.status]||run.status} · V${run.version}${run.selected?' · 已选用':''}`));
      if(!matching||!run.applicable)card.append(node('p','历史记录 / 当前不可选用','hint'));
      if(run.error)card.append(node('p',run.error,'hint'));
      if(run.status==='unknown')card.append(node('p','请核对服务端结果；不会自动重试。','hint'));
      if(run.status==='running')card.append(node('p','标记结果未知不会取消外部生成请求。','hint'));
      const action=(text,suffix)=>{const button=node('button',text,'secondary');button.type='button';button.dataset.mediaAction=suffix;button.dataset.applicable=String(!!run.applicable&&matching);button.onclick=()=>busy(async()=>{
        if(suffix==='select'&&!editable())throw new Error('请先保存并确认当前分镜。');
        await api(endpoint()+'/'+encodeURIComponent(run.id)+'/'+suffix,suffix==='select'?{expected_version:current.version}:{});await refresh();
      });card.append(button);};
      if(run.status==='succeeded'&&run.media_url)action(run.selected?'已选用':'选用此图','select');
      if(run.status==='queued')action('取消排队','cancel');
      if(run.status==='running')action('标记结果未知','abandon');
      candidates.append(card);
    }
    availability();
  }
  function availability() {
    const pending=current&&readMemory(pendingKey()), ready=editable()&&loadedFor===identity();
    if(pending){
      const value=pending.profile.profile_id+':'+pending.profile.version;
      if(![...$('image-profile').options].some(o=>o.value===value)){const option=node('option','上次图片请求配置 · V'+pending.profile.version);option.value=value;$('image-profile').append(option);}
      $('image-profile').value=value;$('frame-role').value=pending.frame_role;$('frame-prompt').value=pending.prompt;$('image-size').value=pending.size;
      $('media-shot').textContent=`${pending.shot_key} / ${roles[pending.frame_role]} · 待恢复请求`;
    }
    // Checking a stored request never creates a new intent: keep its original version/key.
    $('generate-image').disabled=working||(pending?!current:(!ready||!$('image-profile').value||!shot()));
    $('generate-image').textContent=pending?'核对上次图片请求':'生成图片候选';
    $('preview-frame-prompt').disabled=working||!ready||!!pending||!shot();
    $('refresh-media').disabled=working||!current;
    $('preview-video-input').disabled=working||!ready||!runs.some(r=>r.selected&&r.applicable&&r.version===current?.version&&r.shot_key===shot()?.key&&r.frame_role==='first');
    for(const id of ['image-profile','frame-role','frame-prompt','image-size'])$(id).disabled=working||!!pending||!ready;
    $('media-status').textContent=pending?`上次图片请求尚未确认接收（${pending.shot_key} / ${roles[pending.frame_role]} / V${pending.expected_version}）。恢复会使用原请求，请先刷新记录。`:dirty?'分镜有未保存修改，请保存并确认后制作。':!current?.confirmed?'请先人工确认当前分镜，再制作图片。':readonly()?'历史版本或来源已变化，仅供查看。':loadedFor!==identity()?'请刷新图片记录后继续。':'提示词修改仅用于本次图片，不会改写已确认分镜。';
    for(const button of $('media-candidates').querySelectorAll('button'))button.disabled=working||(button.dataset.mediaAction==='select'&&(!ready||button.dataset.applicable!=='true'));
  }
  async function refresh() {
    loadedFor='';runs=[];render();if(!current)return;
    const requested=identity();
    try {
      const result=await api(endpoint()+'?version='+current.version);if(requested!==identity())return;
      runs=result.runs||[];loadedFor=requested;
      const pending=readMemory(pendingKey());if(pending&&runs.some(r=>r.idempotency_key===pending.idempotency_key)){memory(pendingKey(),null);context='';}
      render();if(typeof renderShots==='function')renderShots();
    }catch(e){$('media-status').textContent='图片记录未能加载：'+e.message;}
  }
  function thumbnail(key) {
    if(loadedFor!==identity())return null;
    const run=runs.find(r=>r.shot_key===key&&r.version===current?.version&&r.selected&&r.frame_role==='first');
    return run?image(run.media_url,key+' 已选首帧'):null;
  }
  $('frame-role').onchange=render;
  $('image-profile').onchange=availability;
  $('frame-prompt').oninput=()=>memory(promptKey(),$('frame-prompt').value);
  $('refresh-media').onclick=()=>busy(refresh);
  $('preview-video-input').onclick=()=>busy(async()=>{
    const packet=await api(boardUrl()+'/video-input?version='+current.version+'&shot_key='+encodeURIComponent(shot().key));
    const target=$('video-input-preview');target.replaceChildren();
    const img=image(packet.first_frame.url,'本镜视频输入首帧');if(img){img.style.maxWidth='240px';target.append(img);}
    target.append(node('p',`计划时长：${packet.duration_ms/1000} 秒 · 尚未提交视频生成`),node('pre',packet.prompt));
    if(packet.manifest.requires_audio_capability)target.append(node('p','本镜含声音要求；接入服务时需核对音频能力。','hint'));
  });
  $('preview-frame-prompt').onclick=()=>busy(async()=>{
    const result=await api(boardUrl()+'/frame-prompt?version='+current.version+'&shot_key='+encodeURIComponent(shot().key)+'&frame_role='+$('frame-role').value);
    $('frame-prompt').value=result.prompt;memory(promptKey(),result.prompt);
  });
  $('image-form').onsubmit=e=>{e.preventDefault();busy(async()=>{
    let payload=readMemory(pendingKey());
    if(!payload&&!editable())throw new Error('请先保存并确认当前分镜。');
    if(!payload){const [profile_id,version]=$('image-profile').value.split(':');payload={expected_version:current.version,shot_key:shot().key,frame_role:$('frame-role').value,profile:{profile_id,version:Number(version)},prompt:$('frame-prompt').value.trim(),size:$('image-size').value.trim(),idempotency_key:crypto.randomUUID().replaceAll('-','')};}
    memory(pendingKey(),payload);
    try {await api(endpoint(),payload);memory(pendingKey(),null);context='';}
    catch(e){if([400,404,409,422].includes(e.status)){memory(pendingKey(),null);context='';render();}throw e;}
    await refresh();notice('图片请求已接收；请刷新记录查看进度。');
  });};
  $('image-config-form').onsubmit=e=>{e.preventDefault();busy(async()=>{
    const item=await api(prefix+'/model-profiles',{name:$('image-config-name').value,purpose:'image',adapter:'openai_images',reasoning_protocol:'none',base_url:$('image-config-url').value,model:$('image-config-model').value,api_key_env:$('image-config-env').value.trim()});
    await profiles(item.id+':'+item.version,'image');$('image-config-details').open=false;notice('图像配置已保存，尚未验证服务连接。');
  });};
  return {setProfiles,availability,render,refresh,thumbnail};
})();

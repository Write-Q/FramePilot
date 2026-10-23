'use strict';
/* Shared, dependency-free assistant shell. Workspace nodes keep their listeners and state. */
window.FramePilotStudio=(()=>{
  const stages={writer:'编剧',storyboard:'分镜',editing:'剪辑'};
  const efforts={default:'默认',none:'关闭',minimal:'极低',low:'低',medium:'中',high:'高',xhigh:'极高',max:'最高'};
  const statuses={pending:'待确认',executing:'执行中',accepted:'已完成',succeeded:'已完成',rejected:'已拒绝',failed:'执行失败',unknown:'结果未知',stale:'来源已变化',completed:'已完成'};
  const read=(key,fallback=null,area=localStorage)=>{try{return JSON.parse(area.getItem('framepilot:studio:'+key))??fallback;}catch{return fallback;}};
  const write=(key,value,area=localStorage)=>{try{if(value===null)area.removeItem('framepilot:studio:'+key);else area.setItem('framepilot:studio:'+key,JSON.stringify(value));}catch{}};
  const key=()=>globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const button=(text,action,cls='studio-button')=>{const n=node('button',cls,text);n.type='button';n.addEventListener('click',action);return n;};
  const plain=value=>typeof value==='string'?value:JSON.stringify(value,null,2);
  async function request(path,body){
    let response;
    try{response=await fetch(path,body===undefined?{headers:{Accept:'application/json'}}:{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify(body)});}catch{throw Object.assign(new Error('连接中断，尚不能确认请求结果。'),{unknown:true});}
    let data;try{data=await response.json();}catch{throw Object.assign(new Error('服务没有返回可读取的结果。'),{unknown:true});}
    if(!response.ok){const detail=typeof data.detail==='string'?data.detail:plain(data.detail||data.error||'请求失败');throw Object.assign(new Error(detail),{status:response.status,unknown:response.status>=500});}
    const result=data.thread||data;
    if(!result||typeof result!=='object')throw Object.assign(new Error('会话结果格式不完整，请刷新读取。'),{unknown:true});
    return result;
  }
  function mount(options){
    if(!options?.workspace)throw new Error('FramePilotStudio needs a workspace element');
    if(document.querySelector('#studio-root'))return window.FramePilotStudio.current;
    const stage=options.stage||'writer',workspace=options.workspace;
    const root=node('div','studio-root');root.id='studio-root';root.dataset.mobile='assistant';
    const nav=node('header','studio-nav');nav.id='studio-nav';nav.setAttribute('aria-label','制作工作台');
    const brand=node('a','studio-brand','FramePilot');brand.href='/';nav.append(brand);
    const stageNav=node('nav','studio-stages');stageNav.setAttribute('aria-label','制作阶段');nav.append(stageNav);
    const links=Object.entries(stages).map(([value,label])=>{const a=node('a','studio-stage',label);a.dataset.stage=value;if(value===stage)a.setAttribute('aria-current','page');stageNav.append(a);return a;});
    const restore=button('展开助手',()=>collapse(false),'studio-button studio-restore');restore.id='assistant-restore';restore.hidden=true;nav.append(restore);
    const mobile=node('div','studio-mobile-tabs');mobile.setAttribute('role','group');mobile.setAttribute('aria-label','切换面板');
    const chatTab=button('助手',()=>showMobile('assistant')),workspaceTab=button('工作区',()=>showMobile('workspace'));mobile.append(chatTab,workspaceTab);
    const panel=node('aside','studio-assistant');panel.id='assistant-panel';panel.setAttribute('aria-label','制作助手');
    const panelHead=node('div','studio-assistant-header');const heading=node('h2','','制作助手');
    const refreshButton=button('刷新会话',()=>refresh(),'studio-button studio-text-button');refreshButton.title='重新读取会话，不重新发送请求';
    const collapseButton=button('收起助手',()=>collapse(true),'studio-button studio-text-button');
    panelHead.append(heading,refreshButton,collapseButton);
    const scope=node('div','studio-context');scope.id='assistant-context';scope.setAttribute('aria-label','当前工作上下文');
    const notice=node('div','studio-notice');notice.id='assistant-notice';notice.hidden=true;notice.setAttribute('role','status');
    const messages=node('div','studio-messages');messages.id='assistant-messages';messages.setAttribute('role','log');messages.setAttribute('aria-label','助手会话');messages.setAttribute('aria-live','polite');messages.setAttribute('aria-relevant','additions text');
    const form=node('form','studio-composer');form.id='assistant-composer';
    const status=node('p','studio-status','连接会话中…');status.id='assistant-status';status.setAttribute('role','status');
    const recovery=node('div','studio-recovery');
    const attachment=node('div','studio-attachment');attachment.hidden=true;
    const input=node('textarea');input.id='assistant-input';input.rows=3;input.placeholder='告诉助手你想推进什么…';input.setAttribute('aria-label','给制作助手的消息');input.maxLength=8000;input.value=read('composer-draft','',sessionStorage);
    const tools=node('div','studio-composer-tools');
    const modelLabel=node('label','studio-control');modelLabel.append(node('span','studio-sr-only','助手模型'));const model=node('select');model.id='assistant-model';model.setAttribute('aria-label','助手模型');modelLabel.append(model);
    const effortLabel=node('label','studio-control studio-effort-control');effortLabel.append(node('span','studio-sr-only','思考等级'));const effort=node('select');effort.id='assistant-effort';effort.setAttribute('aria-label','思考等级');effortLabel.append(effort);
    const attachButton=button('引用选区',attachSelection,'studio-button studio-text-button');attachButton.title='将工作区当前选中的文字附在下一条消息中';
    const send=button('发送',()=>{} ,'studio-button studio-send');send.type='submit';send.setAttribute('aria-label','发送消息');
    tools.append(modelLabel,effortLabel,attachButton,send);
    const configLink=node('a','studio-config-link','配置助手文本模型');configLink.href='/storyboard#config-details';configLink.hidden=true;
    const hint=node('p','studio-composer-hint','Enter 发送 · Shift + Enter 换行');
    form.append(status,recovery,attachment,input,tools,configLink,hint);panel.append(panelHead,scope,notice,messages,form);
    const separator=node('div','studio-separator');separator.id='studio-separator';separator.tabIndex=0;separator.setAttribute('role','separator');separator.setAttribute('aria-orientation','vertical');separator.setAttribute('aria-label','调整助手宽度');separator.setAttribute('aria-valuemin','300');separator.setAttribute('aria-valuemax','560');separator.setAttribute('aria-controls','assistant-panel');
    const work=node('section','studio-workspace');work.id='studio-workspace';work.setAttribute('aria-label',stages[stage]+'工作区');
    const workHeading=node('div','studio-workspace-heading');const workTitle=node('h1');const workMeta=node('p');workHeading.append(workTitle,workMeta);
    document.body.classList.add('studio-mounted');document.body.insertBefore(root,document.body.firstChild);root.append(nav,mobile,panel,separator,work);work.append(workHeading,workspace);
    let context={},thread=null,binding=null,epoch=0,busy=false,pending=null,profiles=[],selected='',selection=null,poll=null,disposed=false;
    const knownResults=new Set();
    let width=Math.max(300,Math.min(560,Number(read('width',360))||360));
    function resize(value){width=Math.max(300,Math.min(560,value));root.style.setProperty('--assistant-width',width+'px');separator.setAttribute('aria-valuenow',String(width));write('width',width);}
    resize(width);
    function collapse(value){root.classList.toggle('studio-assistant-collapsed',value);restore.hidden=!value;collapseButton.setAttribute('aria-expanded',String(!value));write('collapsed',value);if(value)restore.focus();else input.focus();}
    if(read('collapsed',false)){root.classList.add('studio-assistant-collapsed');restore.hidden=false;}
    function showMobile(value){root.dataset.mobile=value;chatTab.setAttribute('aria-pressed',String(value==='assistant'));workspaceTab.setAttribute('aria-pressed',String(value==='workspace'));}
    showMobile('assistant');
    separator.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();resize(event.key==='Home'?300:event.key==='End'?560:width+(event.key==='ArrowRight'?20:-20));}});
    separator.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();const start=event.clientX,initial=width;separator.setPointerCapture(event.pointerId);root.classList.add('studio-resizing');const move=e=>resize(initial+e.clientX-start);const end=()=>{separator.removeEventListener('pointermove',move);separator.removeEventListener('pointerup',end);separator.removeEventListener('pointercancel',end);root.classList.remove('studio-resizing');};separator.addEventListener('pointermove',move);separator.addEventListener('pointerup',end);separator.addEventListener('pointercancel',end);});
    function currentContext(){let fresh={};try{fresh=options.getContext?.()||{};}catch{}return {...context,...fresh,stage,project_id:Object.prototype.hasOwnProperty.call(fresh,'project_id')?fresh.project_id:context.project_id??null};}
    function projectOf(ctx){return ctx.project_id?String(ctx.project_id):null;}
    function setNotice(text,type='info'){notice.textContent=text||'';notice.hidden=!text;notice.dataset.type=type;}
    function updateLinks(){const ctx=currentContext();[...links,configLink].forEach(a=>{const url=new URL(a===configLink?'/storyboard':a.dataset.stage==='writer'?'/':'/'+a.dataset.stage,location.origin);if(ctx.project_id)url.searchParams.set('project',ctx.project_id);if(ctx.storyboard_id)url.searchParams.set('board',ctx.storyboard_id);if(thread?.id&&thread.project_id===projectOf(ctx))url.searchParams.set('thread',thread.id);if(a===configLink)url.hash='config-details';a.href=url.pathname+url.search+url.hash;});}
    function renderContext(){const ctx=currentContext();scope.replaceChildren(node('span','studio-context-stage',stages[stage]));if(ctx.project_id){const p=node('span','studio-context-detail',ctx.project_label||'项目 '+ctx.project_id);p.title=ctx.project_label||ctx.project_id;scope.append(p);}else scope.append(node('span','studio-context-detail','未绑定项目'));if(ctx.version_label||ctx.source_version||ctx.version)scope.append(node('span','studio-context-detail',ctx.version_label||'V'+(ctx.source_version||ctx.version)));if(ctx.shot_key){const shot=button('镜头 '+ctx.shot_key,()=>options.onNavigateReference?.({project_id:ctx.project_id,storyboard_id:ctx.storyboard_id,shot_key:ctx.shot_key}),'studio-context-reference');scope.append(shot);}workHeading.hidden=![ctx.project_label,ctx.version_label,ctx.save_label,ctx.context_label].some(Boolean);workTitle.textContent=ctx.project_label||stages[stage]+'工作区';workMeta.textContent=[ctx.version_label,ctx.save_label,ctx.context_label].filter(Boolean).join(' · ');updateLinks();}
    function profileSync(){const chosen=profiles.find(p=>p.id+':'+p.version===model.value);selected=model.value;const old=effort.value||read('effort:'+selected,'default',sessionStorage);const values=chosen?.reasoning_options?.length?chosen.reasoning_options:['default'];effort.replaceChildren(...values.map(value=>{const o=node('option','',efforts[value]||value);o.value=value;return o;}));effort.value=values.includes(old)?old:values[0];effort.title=values.length===1?'配置未声明其他思考等级，沿用服务默认':'按模型配置声明显示';syncControls();}
    function syncControls(){if(pending?.kind==='message'&&pending.body.profile){const frozen=pending.body.profile.profile_id+':'+pending.body.profile.version;if(![...model.options].some(o=>o.value===frozen)){const o=node('option','','上次请求的模型 · V'+pending.body.profile.version);o.value=frozen;model.append(o);}model.value=frozen;const frozenEffort=pending.body.reasoning_effort||'default';if(![...effort.options].some(o=>o.value===frozenEffort)){const o=node('option','',efforts[frozenEffort]||frozenEffort);o.value=frozenEffort;effort.append(o);}effort.value=frozenEffort;}const configured=profiles.some(p=>p.id+':'+p.version===model.value);send.disabled=!thread||busy||!!pending||thread.active||!configured||!input.value.trim()||thread.project_id!==projectOf(currentContext());model.disabled=busy||!!pending;effort.disabled=busy||!!pending||!configured||effort.options.length<2;configLink.hidden=profiles.length>0;attachButton.disabled=busy;}
    model.addEventListener('change',()=>{write('model',model.value,sessionStorage);profileSync();});effort.addEventListener('change',()=>write('effort:'+model.value,effort.value,sessionStorage));input.addEventListener('input',()=>{write('composer-draft',input.value,sessionStorage);syncControls();});
    let composing=false;input.addEventListener('compositionstart',()=>composing=true);input.addEventListener('compositionend',()=>composing=false);
    input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing&&!composing&&event.keyCode!==229){event.preventDefault();if(!send.disabled)form.requestSubmit();}});
    form.addEventListener('submit',event=>{event.preventDefault();sendMessage();});
    function attachSelection(){const text=String(window.getSelection?.()||'').trim();if(!text){setNotice('先在工作区选中文字，再点击“引用选区”。');return;}selection=text.slice(0,4000);renderAttachment();setNotice(text.length>4000?'选区较长，已引用前 4000 字。':'已将选区附在下一条消息中。');}
    function renderAttachment(){attachment.hidden=!selection;attachment.replaceChildren();if(selection){attachment.append(node('span','','引用：'+selection.slice(0,90)+(selection.length>90?'…':'')),button('移除引用',()=>{selection=null;renderAttachment();},'studio-button studio-text-button'));}}
    function renderRecovery(){recovery.replaceChildren();if(pending){recovery.append(node('p','','上次请求的结果尚未确认。刷新只读取状态；重试沿用原请求。'));const retry=button('重试原请求',()=>runPending(),'studio-button');retry.id='assistant-retry';retry.disabled=busy;recovery.append(retry);}if(thread?.active){const activeMessage=[...(thread.messages||[])].reverse().find(m=>m.role==='assistant'&&['pending','running','executing','unknown'].includes(m.status));if(activeMessage){recovery.append(node('p','','模型仍在处理中。停止等待只会标记结果未知，不会取消服务商请求。'));const mark=button('标记结果未知',()=>abandon(activeMessage.id),'studio-button studio-text-button');mark.disabled=busy;recovery.append(mark);}}}
    function proposalNode(p){
      const block=node('article','studio-proposal');block.dataset.proposal=p.id;
      const head=node('div','studio-proposal-heading');head.append(node('h3','',p.title||'工作区建议'),node('span','studio-proposal-state',statuses[p.status]||p.status||'待确认'));block.append(head);
      if(p.summary)block.append(node('p','',p.summary));
      if(p.preview!==undefined&&p.preview!==null){const details=node('details','studio-proposal-preview');details.open=true;details.append(node('summary','','查看改动预览'));if(typeof p.preview==='object'&&('before'in p.preview||'after'in p.preview)){if('before'in p.preview){details.append(node('h4','','修改前'),node('pre','studio-diff-before',plain(p.preview.before)));}if('after'in p.preview){details.append(node('h4','','修改后'),node('pre','studio-diff-after',plain(p.preview.after)));}}else details.append(node('pre','',plain(p.preview)));block.append(details);}
      if(p.execution_model)block.append(node('p','studio-proposal-meta','执行模型：'+(typeof p.execution_model==='object'?[p.execution_model.model||p.execution_model.profile_id,p.execution_model.version?'V'+p.execution_model.version:''].filter(Boolean).join(' · '):p.execution_model)));
      if(p.may_call_model)block.append(node('p','studio-proposal-meta','接受后将调用配置的模型。'));
      if(p.error)block.append(node('p','studio-proposal-error',plain(p.error)));
      if(p.status==='executing'){const mark=button('标记执行结果未知',()=>abandonProposal(p.id),'studio-button studio-text-button');mark.disabled=busy;block.append(mark,node('p','studio-proposal-meta','仅在长时间无结果或执行中断后使用。此操作不会取消服务商请求。'));}
      if(p.status==='pending'||!p.status){
        const dirty=!!currentContext().workspace_dirty;
        const actions=node('div','studio-proposal-actions');const accept=button('接受并执行',()=>decide(p,'accept'));accept.disabled=busy||!!pending||thread?.active||dirty||p.available===false;const reject=button('拒绝',()=>decide(p,'reject'),'studio-button studio-text-button');reject.disabled=busy||!!pending||thread?.active;actions.append(accept,reject);block.append(actions);
        const reason=dirty?'工作区有未保存的修改。请先保存，再接受建议。':p.available===false?(p.unavailable_reason||'当前上下文无法执行此建议。'):'';if(reason){const reasonNode=node('p','studio-proposal-meta',reason);reasonNode.id='proposal-reason-'+p.id;accept.setAttribute('aria-describedby',reasonNode.id);block.append(reasonNode);}
      }
      if(p.context?.shot_key&&options.onNavigateReference)block.append(button('定位镜头 '+p.context.shot_key,()=>options.onNavigateReference(p.context),'studio-button studio-text-button'));
      return block;
    }
    function renderMessages(){
      const nearBottom=messages.scrollHeight-messages.scrollTop-messages.clientHeight<90,top=messages.scrollTop;
      messages.replaceChildren();const entries=thread?.messages||[];const proposals=thread?.proposals||[];const displayed=new Set();
      if(!entries.length&&!proposals.length){const empty=node('div','studio-empty');empty.append(node('h3','','一起推进这部作品'),node('p','','可以讨论故事、检查分镜，或整理剪辑思路。涉及修改时，助手会先给出建议，等你确认后执行。'));messages.append(empty);}
      entries.forEach(m=>{const article=node('article','studio-message studio-message-'+m.role);article.dataset.message=m.id;const label=node('div','studio-message-label',m.role==='user'?'你':m.role==='assistant'?'制作助手':'会话记录');article.append(label);if(m.context?.stage){const ref=node('span','studio-message-context',stages[m.context.stage]||m.context.stage);label.append(ref);}article.append(node('div','studio-message-text',m.text||''));if(m.status&&['unknown','failed','pending','running','executing'].includes(m.status))article.append(node('span','studio-message-state',statuses[m.status]||'处理中'));(m.proposals||[]).forEach(value=>{const p=typeof value==='string'?proposals.find(x=>x.id===value):proposals.find(x=>x.id===value.id)||value;if(p&&!displayed.has(p.id)){article.append(proposalNode(p));displayed.add(p.id);}});messages.append(article);});
      proposals.filter(p=>!displayed.has(p.id)).forEach(p=>messages.append(proposalNode(p)));
      messages.scrollTop=nearBottom?messages.scrollHeight:top;
    }
    function savePending(value){pending=value;if(thread)write('pending:'+thread.id,value,sessionStorage);renderRecovery();syncControls();}
    function normalizedSummary(value){if(typeof value.id!=='string'||!Number.isInteger(value.revision)||!Array.isArray(value.messages))throw Object.assign(new Error('会话返回不完整，不能确认操作结果。请刷新。'),{unknown:true});return {...value,project_id:value.project_id||null,proposals:value.proposals||[]};}
    async function apply(value,{decisionId=null,initial=false}={}){
      const next=normalizedSummary(value);
      if(next.project_id!==projectOf(currentContext())){
        const creation=next.proposals.find(p=>p.kind==='writer_create'&&['accepted','succeeded','unknown'].includes(p.status));
        if(projectOf(currentContext())!==null||!next.project_id||thread?.id!==next.id||thread.project_id!==null||!creation)throw new Error('会话属于其他项目，已阻止跨项目读取。');
        binding=next.project_id;context.project_id=next.project_id;write('unbound-thread',null);write('create:unbound',null);write('thread:'+next.project_id,next.id);
        const target=new URL(location.href);target.searchParams.set('project',next.project_id);history.replaceState(history.state,'',target.pathname+target.search+target.hash);
        if(['accepted','succeeded'].includes(creation.status))knownResults.add(next.id+':'+creation.id);
        try{await options.onResult?.(creation.result?.stage?creation.result:{project_id:next.project_id,stage:'writer',result:creation.result});}catch(error){setNotice('项目已创建，请重新读取工作区：'+error.message,'error');}
      }
      thread=next;root.dataset.thread=thread.id;
      if(initial)thread.proposals.filter(p=>['accepted','succeeded'].includes(p.status)).forEach(p=>knownResults.add(thread.id+':'+p.id));
      const ctx=currentContext();write(ctx.project_id?'thread:'+ctx.project_id:'unbound-thread',thread.id);
      const url=new URL(location.href);url.searchParams.set('thread',thread.id);history.replaceState(history.state,'',url.pathname+url.search+url.hash);
      renderContext();renderMessages();syncControls();
      status.textContent=thread.active?'助手正在处理，可刷新查看结果':pending?'上次请求结果待确认':'已连接';
      if(decisionId){const p=thread.proposals.find(x=>x.id===decisionId);const resultKey=thread.id+':'+decisionId;if(['accepted','succeeded'].includes(p?.status)&&!knownResults.has(resultKey)){knownResults.add(resultKey);const result=p.result?.stage?p.result:{project_id:thread.project_id,stage:p.context?.stage||stage,storyboard_id:p.context?.storyboard_id||ctx.storyboard_id,result:p.result};try{await options.onResult?.(result);}catch(error){setNotice('建议已执行，但工作区刷新失败：'+error.message+'。请手动刷新工作区。','error');}}}
      clearTimeout(poll);if(thread.active&&!disposed)poll=setTimeout(()=>{if(!document.hidden)refresh();},3000);
    }
    async function bind(){
      const ctx=currentContext(),project=projectOf(ctx),generation=++epoch;binding=project;thread=null;pending=null;knownResults.clear();root.removeAttribute('data-thread');status.textContent='连接会话中…';setNotice('');renderMessages();renderContext();syncControls();
      const requested=new URL(location.href).searchParams.get('thread');let candidate=project?read('thread:'+project):requested||read('unbound-thread');
      try{
        let data=null;
        if(candidate){try{const found=normalizedSummary(await request('/api/assistant/threads/'+encodeURIComponent(candidate)));if(found.project_id===project||(!project&&candidate===read('unbound-thread')&&found.proposals.some(p=>p.kind==='writer_create'&&['accepted','succeeded','unknown'].includes(p.status))))data=found;}catch(error){if(error.status!==404&&error.status!==403)throw error;}}
        if(!data){const storageKey='create:'+(project||'unbound');let token=read(storageKey);if(!token){token=key();write(storageKey,token);}data=await request('/api/assistant/threads',{...(project?{project_id:project}:{}),idempotency_key:token});}
        if(generation!==epoch)return;
        thread={...normalizedSummary(data),project_id:project};pending=read('pending:'+thread.id,null,sessionStorage);
        await apply(data,{initial:true});renderRecovery();
      }catch(error){if(generation!==epoch)return;status.textContent='连接失败';setNotice(error.message+' 点击“刷新会话”重试连接。','error');syncControls();}
    }
    async function refresh(){
      if(projectOf(currentContext())!==binding||!thread){return bind();}if(busy)return;
      const generation=epoch,id=thread.id;status.textContent='正在读取会话…';
      try{const data=await request('/api/assistant/threads/'+encodeURIComponent(id));if(generation!==epoch)return;await apply(data,{decisionId:pending?.kind==='decision'?pending.proposalId:null});renderRecovery();}catch(error){if(generation!==epoch)return;status.textContent='读取失败';setNotice(error.message+' 可以再次刷新会话。','error');}
    }
    async function runPending(){
      if(!pending||busy||!thread||thread.project_id!==projectOf(currentContext()))return;
      if(pending.kind==='decision'&&pending.body.decision==='accept'&&currentContext().workspace_dirty){setNotice('工作区有未保存的修改。请先保存，再重试执行。','error');return;}
      const operation=pending,generation=epoch;busy=true;setNotice('');status.textContent=operation.kind==='message'?'正在等待助手回复…':'正在提交决定…';renderRecovery();renderMessages();syncControls();
      try{
        const data=await request(operation.path,operation.body);if(generation!==epoch)return;
        await apply(data,{decisionId:operation.kind==='decision'?operation.proposalId:null});
        const outcomeUnknown=operation.kind==='message'?thread.messages.slice(-2).some(m=>m.status==='unknown'):thread.proposals.find(p=>p.id===operation.proposalId)?.status==='unknown';
        if(outcomeUnknown){status.textContent='请求结果未知';setNotice('服务已记录请求，但结果尚未确认。请刷新查看状态，或显式重试原请求。','error');return;}
        savePending(null);if(operation.kind==='message'){if(input.value.trim()===operation.body.text){input.value='';write('composer-draft','',sessionStorage);}selection=null;renderAttachment();}status.textContent=thread.active?'助手正在处理，可刷新查看结果':'已连接';renderMessages();syncControls();
      }catch(error){if(generation!==epoch)return;status.textContent=error.unknown?'请求结果未知':'请求未完成';setNotice(error.message+(error.unknown?' 请先刷新查看状态，或显式重试原请求。':' 请刷新会话后检查。'),'error');if(!error.unknown){savePending(null);if(error.status===409)await refresh();}}
      finally{if(generation===epoch){busy=false;renderRecovery();renderMessages();syncControls();}}
    }
    async function sendMessage(){
      const ctx=currentContext();if(projectOf(ctx)!==binding){await bind();return;}if(send.disabled||!thread)return;
      const chosen=profiles.find(p=>p.id+':'+p.version===model.value);if(!chosen)return;
      const attached=selection||ctx.selection;
      const body={expected_revision:thread.revision,text:input.value.trim(),context:{stage,...(ctx.storyboard_id?{storyboard_id:ctx.storyboard_id}:{}),...(ctx.shot_key?{shot_key:ctx.shot_key}:{}),...(attached?{selection:typeof attached==='string'?attached.slice(0,4000):attached}:{}),workspace_dirty:!!ctx.workspace_dirty},profile:{profile_id:chosen.id,version:chosen.version},reasoning_effort:effort.value||'default',idempotency_key:key()};
      savePending({kind:'message',path:'/api/assistant/threads/'+encodeURIComponent(thread.id)+'/messages',body});await runPending();
    }
    async function decide(p,decision){const ctx=currentContext();if(projectOf(ctx)!==binding){await bind();return;}if(busy||pending||!thread)return;if(decision==='accept'&&(ctx.workspace_dirty||p.available===false)){setNotice('请先保存工作区，并确认建议仍可执行。','error');return;}savePending({kind:'decision',proposalId:p.id,path:'/api/assistant/threads/'+encodeURIComponent(thread.id)+'/proposals/'+encodeURIComponent(p.id)+'/decision',body:{decision,idempotency_key:key(),workspace_dirty:!!ctx.workspace_dirty}});await runPending();}
    async function abandon(id){if(!thread||busy)return;busy=true;syncControls();try{await apply(await request('/api/assistant/threads/'+encodeURIComponent(thread.id)+'/messages/'+encodeURIComponent(id)+'/abandon',{idempotency_key:key()}));savePending(null);setNotice('已标记结果未知。服务端模型请求可能仍在执行；此操作不会取消服务商请求。');}catch(error){setNotice(error.message,'error');}finally{busy=false;syncControls();}}
    async function abandonProposal(id){if(!thread||busy||thread.project_id!==projectOf(currentContext()))return;const generation=epoch;busy=true;syncControls();renderMessages();try{const data=await request('/api/assistant/threads/'+encodeURIComponent(thread.id)+'/proposals/'+encodeURIComponent(id)+'/abandon',{idempotency_key:key()});if(generation!==epoch)return;await apply(data);if(pending?.proposalId===id)savePending(null);setNotice('已标记执行结果未知。服务端模型请求可能仍在执行；此操作不会取消服务商请求。');}catch(error){if(generation===epoch)setNotice(error.message,'error');}finally{if(generation===epoch){busy=false;renderMessages();syncControls();}}}
    async function loadModels(){try{const data=await request('/api/production/model-profiles');profiles=(Array.isArray(data)?data:data.items||data.profiles||[]).filter(p=>p.executable&&p.config?.adapter==='openai_chat'&&p.config?.purpose==='text');model.replaceChildren(...profiles.map(p=>{const o=node('option','',`${p.config.name||p.config.model} · V${p.version}`);o.value=p.id+':'+p.version;o.title=p.config.model;return o;}));if(!profiles.length){const o=node('option','','先配置文本模型');o.value='';model.append(o);}const saved=read('model',null,sessionStorage);if(profiles.some(p=>p.id+':'+p.version===saved))model.value=saved;profileSync();}catch(error){configLink.hidden=false;model.replaceChildren(node('option','','模型配置读取失败'));setNotice('无法读取模型配置：'+error.message,'error');syncControls();}}
    function setContext(value={}){context={...context,...value};renderContext();if(projectOf(currentContext())!==binding){busy=false;bind();}else{renderMessages();syncControls();}}
    const onContext=event=>setContext(event.detail||{});window.addEventListener('framepilot:studio-context',onContext);
    const controller={setContext,refresh,setNotice,destroy(){disposed=true;clearTimeout(poll);window.removeEventListener('framepilot:studio-context',onContext);}};
    window.FramePilotStudio.current=controller;renderContext();syncControls();bind();loadModels();return controller;
  }
  return {mount};
})();

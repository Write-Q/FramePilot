'use strict';
(() => {
  const bridge=window.FramePilotWorkspace;
  if(!bridge||!window.FramePilotStudio)return;
  const workspace=document.querySelector('main');
  const stage=bridge.getContext().stage;
  workspace.classList.add('studio-stage-'+stage);
  const fold=(target,title)=>{if(!target)return;const detail=document.createElement('details');detail.className='studio-tools';const summary=document.createElement('summary');summary.textContent=title;target.before(detail);detail.append(summary,target);};
  if(stage==='writer'){
    fold(workspace.firstElementChild,'创作输入与项目切换');
    const body=document.getElementById('draft')?.closest('details');
    if(body){body.open=true;body.classList.add('studio-script');document.getElementById('summary').after(body);}
  }
  if(stage==='storyboard'){
    fold(workspace.querySelector('aside'),'项目、生成设置与运行记录');
    const board=document.getElementById('board');
    if(board){
      const tabs=document.createElement('nav');tabs.className='studio-stage-tabs';tabs.setAttribute('aria-label','分镜工作视图');
      const groups=[['镜头',board.querySelector('.shot-workspace')],['文字审核',document.getElementById('model-review-panel'),board.querySelector('.review')],['图片素材',document.getElementById('media-panel')],['视频与检查',document.getElementById('video-runtime-panel'),document.getElementById('inspection-panel')]];
      const select=index=>{groups.forEach((g,i)=>{g.slice(1).forEach(n=>{if(n)n.hidden=i!==index;});tabs.children[i].setAttribute('aria-pressed',String(i===index));});};
      groups.forEach((g,i)=>{const button=document.createElement('button');button.type='button';button.textContent=g[0];button.onclick=()=>select(i);tabs.append(button);});
      board.querySelector('.shot-workspace')?.before(tabs);select(0);
      workspace.addEventListener('invalid',e=>{const index=groups.findIndex(g=>g.slice(1).some(n=>n?.contains(e.target)));if(index>=0)select(index);},true);
      workspace.addEventListener('framepilot:show-shot',()=>select(0));
    }
  }
  if(stage==='editing'){
    const clips=document.getElementById('clips')?.closest('section');
    if(clips){const preview=document.createElement('section');preview.className='studio-preview';preview.id='export-preview';preview.setAttribute('aria-label','成片预览');clips.before(preview);}
    for(const [id,title] of [['local-upload-form','素材库'],['subtitles','字幕'],['audio-tracks','音轨'],['exports','成片历史与人工验收']])fold(document.getElementById(id)?.closest('section'),title);
    fold(workspace.querySelector('aside'),'输出设置与时间线版本');
  }
  const controller=window.FramePilotStudio.mount({stage,workspace,
    getContext:()=>bridge.getContext(),
    onResult:async result=>{
      if(result.stage&&result.stage!==stage){
        const target=new URL({writer:'/',storyboard:'/storyboard',editing:'/editing'}[result.stage],location.origin);
        target.searchParams.set('project',result.project_id);
        if(result.storyboard_id)target.searchParams.set('board',result.storyboard_id);
        const thread=new URL(location.href).searchParams.get('thread');if(thread)target.searchParams.set('thread',thread);
        location.assign(target);return;
      }
      await bridge.refresh(result);
    },
    onNavigateReference:ref=>{workspace.dispatchEvent(new Event('framepilot:show-shot'));return bridge.selectReference?.(ref);}
  });
  controller.setContext(bridge.getContext());
  if(location.hash==='#model-settings'||location.hash==='#config-details'){
    const config=document.getElementById('config-details');
    if(config){config.open=true;for(let p=config.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;config.scrollIntoView({block:'start'});}
  }
})();

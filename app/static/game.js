/* 独立游戏页面，使用textContent显示模型输出，避免HTML注入。 */
'use strict';
const $=id=>document.getElementById(id);
let current=null,busy=false,poll=null,candidateText='';
const labels={strength:'体魄',agility:'敏捷',insight:'洞察',social:'交涉'};
function node(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;}
function button(text,fn){const b=node('button',text);b.type='button';b.className='outline';b.onclick=()=>run(fn);return b;}
function notify(text){$('message').textContent=text;}
async function api(path,data,method){const r=await fetch('/api/game'+path,{method:method||(data?'POST':'GET'),headers:{'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined});const value=await r.json();if(!r.ok)throw new Error(typeof value.detail==='string'?value.detail:'输入内容未通过检查。');return value;}
async function run(fn){if(busy)return;busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);try{await fn();}catch(e){notify(e.message);if(current){try{current=await api('/sessions/'+current.id);render();}catch(_){}}}finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);}}
function route(){const by=new Map(current.turns.map(t=>[t.id,t]));let id=current.branches[current.active_branch].head;const out=[];while(id){const t=by.get(id);out.push(t);id=t.parent;}return out.reverse();}
async function load(id){current=await api('/sessions/'+id);localStorage.setItem('framepilot-game',id);render();notify(current.error||'存档已保存。你可以继续行动。');}
async function list(){const data=await api('/sessions');$('sessions').replaceChildren();for(const s of data.sessions)$('sessions').append(button(s.background,()=>load(s.id)));}
function render(){
 $('game').hidden=false;$('opening').open=false;
 $('branch').replaceChildren();for(const [id,b] of Object.entries(current.branches)){const option=node('option',b.name);option.value=id;option.selected=id===current.active_branch;$('branch').append(option);}
 $('stats-toggle').checked=current.show_stats;$('images-toggle').checked=current.auto_images;
 $('budget').textContent=`文字调用 ${current.calls}/100 · 插图 ${current.image_calls}/20 · ${current.image_configured?'生图接口已配置':'生图接口未配置，可继续文字游戏'}`;
 $('export').href=`/api/game/sessions/${current.id}/export`;
 const turns=route(),last=turns.at(-1);$('history').replaceChildren();$('state').textContent=last?`${last.state.scene} · 随身物品：${last.state.inventory.join('、')||'无'}${current.show_stats?' · 生命 '+last.state.hp+'/10 · '+Object.entries(last.state.attributes).map(([k,v])=>labels[k]+v).join(' / '):''}`:'';
 for(const [index,t] of turns.entries()){
  const section=node('section');section.className='turn';section.append(node('h3',`${String(index+1).padStart(2,'0')} / ${t.action}`));const prose=node('div',t.text);prose.className='prose';section.append(prose);
  if(t.result){const roll=node('p',current.show_stats?`${t.result.success?'成功':'失败'}${t.result.die===null?' · 无需检定':` · d20=${t.result.die} + ${labels[t.result.attribute]}${t.state.attributes[t.result.attribute]} / 难度${t.result.difficulty}`} · 生命损失 ${t.result.damage}`:t.result.success?'行动顺利。':'行动遇到了阻碍。');roll.className='roll';section.append(roll);}
  for(const image of current.images.filter(i=>i.turn_id===t.id)){
   if(image.status==='ready'){const img=node('img');img.src=`/api/game/sessions/${current.id}/images/${image.id}`;img.alt=`${t.state.scene}的剧情插图`;img.loading='lazy';section.append(img);}
   else{const status=node('p',image.error||'插图生成中……');status.className='image-status';section.append(status);}
  }
  const actions=node('div');actions.className='actions';if(current.death!=='hardcore')actions.append(button('从这里另开路线',async()=>{current=await api(`/sessions/${current.id}/branches`,{turn_id:t.id,revision:current.revision});await load(current.id);}));
  actions.append(button('画出这一幕',async()=>{await api(`/sessions/${current.id}/images`,{turn_id:t.id});await load(current.id);}));section.append(actions);$('history').append(section);
 }
 $('choices').replaceChildren();if(last&&!current.pending&&last.state.hp>0)for(const choice of last.choices)$('choices').append(button(choice,()=>act(choice)));
 $('act').hidden=!last||last.state.hp===0||Boolean(current.pending);$('recovery').hidden=!current.pending;
 $('cancel').hidden=current.pending?.kind==='open';
 if(last?.state.hp===0)notify(current.death==='hardcore'?'此局结束。你可以新开一局。':'这条路线结束了。可以从历史回合尝试另一条路。');
 clearTimeout(poll);if(current.images.some(i=>['pending','running'].includes(i.status)))poll=setTimeout(async()=>{if(!busy)try{await load(current.id);}catch(e){notify(e.message);}else render();},2500);
}
async function act(action){current=await api(`/sessions/${current.id}/actions`,{action,operation_id:crypto.randomUUID(),branch:current.active_branch,revision:current.revision});$('action').value='';render();notify(current.error||'行动已保存。');}
$('entry').onchange=()=>{$('background-tools').hidden=$('entry').value==='free';$('feedback').disabled=$('entry').value!=='collaborative';};
$('requirements').oninput=()=>{if($('entry').value==='free')$('background').value=$('requirements').value;};
$('suggest').onclick=()=>run(async()=>{notify('正在构建故事背景……');const data=await api('/backgrounds',{requirements:$('requirements').value,feedback:$('entry').value==='collaborative'?candidateText+'\n用户反馈：'+$('feedback').value:''});candidateText=data.backgrounds.join('\n\n');$('candidates').replaceChildren();for(const text of data.backgrounds)$('candidates').append(button(text,async()=>{$('background').value=text;notify('可以修改背景，然后确认开局。');}));notify('选择一个背景，也可以继续提出反馈。');});
$('new-game').onsubmit=e=>{e.preventDefault();run(async()=>{notify('正在进入故事……');current=await api('/sessions',{background:$('background').value,death:$('death').value,show_stats:$('initial-stats').checked,auto_images:$('initial-images').checked});localStorage.setItem('framepilot-game',current.id);render();notify(current.error||'故事开始了。');await list();});};
$('act').onsubmit=e=>{e.preventDefault();run(()=>act($('action').value));};
$('retry').onclick=()=>run(async()=>{if(current.pending.kind==='open')current=await api(`/sessions/${current.id}/open/retry`,{});else current=await api(`/sessions/${current.id}/actions`,{action:current.pending.action,operation_id:current.pending.operation_id,branch:current.active_branch,revision:current.revision});render();notify(current.error||'当前步骤已完成。');});
async function settings(values){await api(`/sessions/${current.id}`,{revision:current.revision,...values},'PATCH');await load(current.id);}
$('cancel').onclick=()=>run(()=>settings({cancel_pending:true}));
$('branch').onchange=()=>run(()=>settings({active_branch:$('branch').value}));
$('stats-toggle').onchange=()=>run(()=>settings({show_stats:$('stats-toggle').checked}));
$('images-toggle').onchange=()=>run(()=>settings({auto_images:$('images-toggle').checked}));
$('refresh').onclick=()=>run(()=>load(current.id));$('reload-list').onclick=()=>run(list);
run(async()=>{await list();const id=localStorage.getItem('framepilot-game');if(id)await load(id);});

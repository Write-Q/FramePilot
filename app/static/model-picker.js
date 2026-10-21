'use strict';
window.ModelPicker=(()=>{
  const states=new Map();
  const labels={default:'默认',none:'关闭',minimal:'极低',low:'低',medium:'中',high:'高',xhigh:'极高',max:'最高'};
  const el=id=>document.getElementById(id);
  const option=(value,text)=>{const node=document.createElement('option');node.value=value;node.textContent=text;return node;};
  function stored(key){try{return sessionStorage.getItem('framepilot:effort:'+key)||'default';}catch{return 'default';}}
  function save(key,value){try{if(key)sessionStorage.setItem('framepilot:effort:'+key,value);}catch{}}
  function sync(modelId,effortId,{pending=null,disabled=false}={}){
    const state=states.get(modelId);if(!state)return;
    const model=el(modelId),effort=el(effortId);
    if(pending){
      const value=pending.profile.profile_id+':'+pending.profile.version;
      if(![...model.options].some(o=>o.value===value))model.append(option(value,'上次请求的模型 · V'+pending.profile.version));
      model.value=value;
    }
    const key=model.value;
    if(state.key&&state.key!==key)save(state.key,effort.value);
    const preferred=pending?(pending.reasoning_effort||'default'):(state.key===key?effort.value:stored(key));
    const profile=state.items.find(p=>p.id+':'+p.version===key);
    const choices=[...(profile?.reasoning_options||['default'])];
    if(pending&&!choices.includes(preferred))choices.push(preferred);
    effort.replaceChildren(...choices.map(value=>option(value,labels[value]||value)));
    effort.value=choices.includes(preferred)?preferred:'default';
    state.key=key;
    model.disabled=disabled||!!pending;
    effort.disabled=disabled||!!pending||!key||choices.length===1;
    effort.title=choices.length===1?'当前配置未声明可选思考等级，沿用服务默认':'按接口配置声明显示；具体模型支持情况仍需验证';
  }
  function setModels(modelId,effortId,items,selected){
    const model=el(modelId),previous=model.value;
    if(!states.has(modelId))states.set(modelId,{items:[],key:null});
    states.get(modelId).items=items;
    model.replaceChildren(...items.map(p=>option(p.id+':'+p.version,`${p.config.model} · ${p.config.name} · V${p.version}`)));
    if(!items.length)model.append(option('','添加模型后选择'));
    if(selected)model.value=selected;
    else if([...model.options].some(o=>o.value===previous))model.value=previous;
    el(effortId).onchange=()=>save(model.value,el(effortId).value);
    sync(modelId,effortId);
  }
  return {setModels,sync};
})();

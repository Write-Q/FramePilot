# AI对话＋工作区执行计划

用户已批准。原生HTML/CSS/JS，左360px可调整/收起的项目对话，右各阶段工作区；<1024px切换对话/工作区，保留草稿和滚动。克制浅绿、无嵌套卡片、紧凑标题与操作。

## 接口契约
- POST /api/assistant/threads {project_id?:str,idempotency_key:str}; GET /api/assistant/threads/{id}
- POST /api/assistant/threads/{id}/messages {expected_revision:int,text:str,context:{stage:writer|storyboard|editing,storyboard_id?:str,shot_key?:str,selection?:str,workspace_dirty:bool},profile:{profile_id,version},reasoning_effort:default|...,idempotency_key}
- POST /api/assistant/threads/{id}/proposals/{pid}/decision {decision:accept|reject,idempotency_key,workspace_dirty:bool}
- POST /api/assistant/threads/{id}/messages/{turn}/abandon：人工标未知，不重新付费；GET记录恢复状态。
- thread summary {id,project_id,revision,messages:[{id,role:user|assistant|system,text,status,context,created_at,proposals?:[]}],proposals:[{id,kind,title,summary,params,preview,execution_model,may_call_model,available,unavailable_reason,status,result,error,context}],active:bool}
- AssistantActions(store,stories,storyboard_provider=None,review_provider=None): context(project_id,context_dict)->dict，内含fingerprint/context数据/available_actions；prepare(project_id,context_snapshot,proposal_dict)->dict（纯校验且生成preview/model/cost/available）；execute(project_id,proposal_dict,idempotency_key,reserved_project_id=None)->{project_id,stage,storyboard_id?,result}。
- 对话服务AssistantService(store,actions,planner=None)：create(request),read(id),message(id,request),decide(id,pid,request),abandon(id,turnid)。先落账后外部调用；冻结对话配置/思考/上下文，JSON输出{reply,proposals:[{kind,title,summary,params}]}。默认使用ChatPlanner。
- 可执行白名单 writer_create/choose/revise/clarify，storyboard_generate/revise/review，image_generate/select，video_select/inspect，timeline_save，export_create。不含最终确认/验收、文件路径、URL、代码工具。

## 执行检查
- [ ] 后端0013新增thread/turn/proposal/execution账本，未绑定项目线程可绑定一次，项目唯一线程；线程一个活动请求；原请求重放、晚到结果不覆盖终态。
- [ ] 上下文仅当前项目已保存状态、选中对象和引用；最近20条/48000字符有界；模型文本是数据不执行。脏草稿禁止确认，OCC和业务原规则保留。
- [ ] 共享studio-ui.css/js供旧页调用，安全文本渲染，模型+effort、选中内容引用、提案预览/确认、会话恢复、resize/mobile。
- [ ] 三页轻量接入，writer项目URL加载，boardURL尊重指定series；操作结果刷新并定位当前工作区，不重建丢草稿。
- [ ] 规格/质量审查；隔离数据库+浏览器测试；业务备份/恢复/全表指纹/schema检查后0013升级；阶段提交推送。

# FramePilot 数据库领域设计草案

状态：待业务评审；本文件不是已实施结构，也不是可直接执行的 SQL。依据现有 models.py、storage.py、domain.py 和本任务关于项目、章节、资产的讨论。目标是稳定归属与版本边界，减少结构返工；不能保证以后无需迁移。

## 方案选择

推荐：关系表管理身份、归属、引用、版本和执行；JSONB 保存按类型校验的设定及模型输出。相比按每种资产复制一套表，它能统一历史与引用管理；相比把所有东西放进项目快照，它能支持可靠约束和查询。JSONB 不承担外键关系，不使用无限扩展的键值属性表。

## 第一版业务边界（建议）

- 项目是一部作品；章节是可独立创作的单元。短片自动创建一个默认章节，界面可隐藏章节导航。
- 本轮保持单用户；不假装具备权限隔离。多用户账号、工作区成员、权限属于未来独立设计范围。
- 每章一个剧本身份、线性版本历史；暂不实现分支合并。版本历史不可覆盖；回退以新版本表达。
- 资产分人物、地点、道具；项目内共有或限定一个章节。跨项目复用先复制并保留来源，绝不隐式引用其他项目的资产。
- AI 提取产生候选设定，人工确认后才能成为正式资产版本；不自动覆盖已确认设定。
- 章节引用表示使用意图；剧本发布/确认时冻结确切资产版本，历史展示不追随最新资产。
- 项目归档可恢复；永久删除及物理文件清理不纳入第一批功能。

## 表的职责与关键字段

内部 id 保持现有兼容的字符串标识；新增对象采用统一生成的 UUID 字符串。时间均使用带时区时间；名称非唯一、不作为关联键。表名为建议名，迁移时保留已有物理表兼容层。

| 表 | 关键字段 | 职责 |
| --- | --- | --- |
| projects | id, name, synopsis, created_at, updated_at, last_opened_at, archived_at, row_version | 作品目录，乐观锁用于拒绝过期修改；项目状态不直接等于某章审核状态 |
| project_brief_versions | id, project_id, version_no, content, schema_version, created_at | 不可变的作品主题、全局风格和约束；确认记录单独管理，任务固定所用版本 |
| chapters | id, project_id, title, position, archived_at, row_version | 章节身份与排序；不把篇幅修改塞进身份记录 |
| chapter_input_versions | id, project_id, chapter_id, version_no, original_story, constraints, created_at | 用户输入与要求历史；首次输入永远保留，后续补充不改写最初原稿 |
| scripts | id, project_id, chapter_id, current_version_id, row_version | 章节剧本身份；第一版每章最多一个 |
| script_versions | id, project_id, script_id, version_no, parent_version_id, input_version_id, brief_version_id, body, card, schema_version, created_at | 不可变正文与当版概括；版本 1 无父版本，后续父版本必须属于本剧本 |
| assets | id, project_id, asset_type, scope_chapter_id, display_name, archived_at, row_version | 资产身份；scope_chapter_id 为空表示项目级，可复用但不意味着每章必用 |
| asset_versions | id, project_id, asset_id, version_no, definition, schema_version, created_at | 不可变设定快照，definition 按人物/地点/道具 Pydantic 模型校验 |
| asset_version_decisions | id, project_id, asset_version_id, decision, reason, created_at | 追加确认/拒绝/撤销记录；内容版本不随审批改变；尚无确认记录视为候选 |
| chapter_asset_links | project_id, chapter_id, asset_id, selected_version_id | 当前章节资产选择；不是历史剧本的版本依据 |
| script_asset_refs | project_id, script_version_id, asset_id, asset_version_id | 剧本版本固定引用；同一剧本版本内一个资产只选择一版基础设定 |
| asset_origins | id, project_id, asset_version_id, source_script_version_id, source_quote | 候选设定的文本依据，可多条；手工建立的资产可以没有来源引用 |
| review_runs | id, project_id, script_version_id, task_id, rubric_version, result, created_at | 每次审核独立存档；仅澄清可以对同一剧本版本创建新审核 |
| review_issues | id, project_id, review_run_id, category, description, suggestion, evidence, needs_user, fingerprint | 每轮问题独立身份；fingerprint 仅用于相似问题关联，不作为跨轮唯一主键 |
| review_issue_assets | project_id, review_issue_id, asset_version_id | 问题关联具体资产版本；十维卡片关联可保留受校验的维度列表 |
| revision_requests | id, project_id, script_id, base_version_id, review_run_id, action, feedback, idempotency_key, created_at | 用户一次明确提交；记录修改、澄清、确认的不同语义；选择方向也保留执行上下文 |
| issue_decisions | id, project_id, request_id, issue_id, choice, instruction | 采用/替换/保留/接受现状分开记录，不用一个布尔值混淆 |
| generation_tasks | id, project_id, chapter_id, request_id, input_manifest, workflow_version, status, result_version_id, row_version, created_at, finished_at | 一次执行；input_manifest 固定输入版本，关系约束依赖明确引用列/关联表而非裸 JSON ID |
| task_attempts | id, task_id, attempt_no, status, started_at, finished_at, error_code | 重试历史独立保存；重试不覆盖上次失败 |
| model_calls（已有 fp_calls 扩展） | id, project_id, task_attempt_id, task, status, provider, model, usage, timestamps | 每次调用账本，失败也计费/计次；与生成任务一对多 |
| workflow_sessions | id, project_id, chapter_id, task_id, thread_id, workflow_version | 业务执行和 LangGraph 检查点之间的映射；检查点不是业务历史版本 |

## 后续制作域：现在明确边界，实施时单独细化

- 场景拆解采用 breakdown_versions 和 scenes：一份拆解固定来源剧本版本，各场戏属于该拆解版本；不把地点资产当成一场戏。
- 镜头采用 storyboard_versions 和 shots：每个分镜版本固定拆解版本，镜头顺序及内容不覆盖已确认分镜。
- 剧情状态变化记录到场戏/镜头上下文，如衣服湿了、道具换人；不能回写基础资产为永久设定。
- media_files 保存 storage_key、媒体类型、校验值、大小和创建时间，不把二进制放入 JSONB，不长期保存会过期的签名 URL。
- asset_media_links 与 shot_media_links 连接确切版本和媒体文件；不使用没有外键校验的通用 target_type/target_id 代替业务关系。
- 生成参数、模型与提示词版本、输入媒体及输出文件需要留痕；素材清理由引用检查和保留策略决定，不能删除资产时直接递归删文件。
- RAG 是检索派生数据：以原始资料/资产版本为来源，记录分块、嵌入模型与索引版本；不作为资产事实源。本轮不锁定向量维度或生成平台专用字段。

## 数据约束

1. 资产版本唯一 (asset_id, version_no)，剧本版本唯一 (script_id, version_no)，输入及设定版本同理。
2. 关系路径统一带 project_id；父表提供 (project_id,id) 唯一键，子表使用组合外键阻止跨项目关联。
3. 引用资产版本时使用 (project_id,asset_id,asset_version_id) 对应组合外键，避免把同一项目另一资产的版本接错。
4. 当前剧本版本指针与父版本指针必须属于同一剧本；selected_version_id 必须属于被引用资产。
5. 章节范围不能仅靠外键保证：章节资产连接需检查 scope_chapter_id 为空或等于引用章节。使用数据库约束触发器并在事务内锁定资产归属，修改范围时也检查既有引用；服务层校验提供中文错误。
6. 有效章节顺序在同项目内唯一；排序操作在事务中完成，使用可延迟约束或先腾挪位置，避免交换顺序时冲突。
7. 版本号分配必须在锁定父对象的短事务内完成，不能裸用 max+1；模型调用期间不持有数据库事务锁。
8. 正文版本及固定资产引用同事务写入；确认前校验引用版本已确认。资产最新版本的产生不自动更新旧引用。
9. 用户提交带 base_version、row_version 和幂等键；过期操作拒绝，重复请求返回同一结果，不能多生成一版。
10. 默认限制删除有历史引用的记录，界面使用归档；审批、执行状态可以变化，但设定/正文内容不可覆盖。不可变规则通过仓库写接口和数据库权限/触发器落实。
11. 索引优先覆盖项目更新时间列表、章节顺序、资产类型与归属、历史版本倒序、待处理任务及调用时间；JSONB 索引依据实际查询添加，不对所有 JSON 字段盲建索引。

## 额度与状态边界

现有 10 次调用上限是项目级，迁移不能把它悄悄变成每章 10 次或重置已用量。第一步保留项目总额度和账本。后续章节/任务限额必须与项目总额同时校验；重试累计计数。业务项目、章节完成状态、一次任务执行状态分开；审核通过与用户确认分开，不宣称机器已经证明质量。

## 现有数据迁移路径

1. 停止写入并备份 PostgreSQL；先做可回滚演练，不直接在唯一数据副本上试迁移。
2. 增量添加新表/列。每个旧项目生成默认章节及剧本身份；旧 project_id 不变，原文、约束、正文版本及调用记录保持映射。缺失历史时间不能伪造，单独标明迁移时间。
3. fp_versions 现有主键 (project_id,version) 先保留，添加新版本 ID 和 script_id，回填后验证数量、正文散列、来源及唯一约束。禁止删除旧正文再重建。
4. 旧检查点继续绑定旧 thread_id 与旧工作流版本；正在等待用户的流程不能直接改状态结构。提供旧流程兼容恢复或在安全停止点显式迁移；新章节流程使用新的执行标识。
5. 更新业务读写并保持旧项目 URL/API 可用；源数据确定后避免两套权威状态互相覆盖。快照用于恢复/缓存，正文与版本表作为业务历史权威来源。
6. 验证后才收紧非空与约束；清理旧字段另做迁移，不能与初次数据迁移同时删除回退依据。

## 验收清单

- 两个项目都有同名人物，任何读取/引用/修改不得串项目。
- 修改人物名称不破坏历史引用；新增设定版本不会改变旧剧本的设定。
- 章节独有资产不能被另一章引用；提升为共有不复制身份；缩小范围时有引用则拒绝。
- 同章不同版本、不同章相同版本号可并存；并发写入不能重复或覆盖版本。
- AI 候选不能覆盖已确认资产；澄清不改正文版本，审核历史仍保留。
- 模型失败/重试保留任务、尝试及调用账本；额度不因重启/新增章节被意外重置。
- 旧项目、旧版本、待确认检查点在迁移前后均可读；失败回滚不损失原稿。

## 本轮评审重点

建议先确认：一项目可多章节但短片默认单章；每章独立线性剧本历史；资产项目内共享或章节独有；引用固定版本；保持单用户与现有总额度。跨项目公共资产库、多人协作、剧本分支合并不纳入当前范围。以上选择确认后再形成逐列类型/长度/可空性字典、完整约束 DDL 与 Alembic 实施计划，不以此草案宣称数据库已设计完成或迁移完成。

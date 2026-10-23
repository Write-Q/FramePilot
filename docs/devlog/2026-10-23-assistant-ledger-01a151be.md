---
title: AI 对话账本与显式提案确认
date: 2026-10-23
status: implementation-verified-awaiting-integration
---

## 需求与决策

- 用户批准三阶段 AI 对话及用户确认后执行提案；本子任务负责持久化与迁移，主任务负责 API、工作区整合及提交推送。
- `AssistantService(store, actions, planner=None)` 使用可注入的动作与模型边界。模型和业务动作调用前落账，调用期间不持有会话或项目数据库锁。
- 对话调用独立记账，不占 writer 的 10 次生成预算。配置和 reasoning effort 按明确版本冻结。revision 仅在消息预留时递增，状态恢复通过重新 GET 获取。
- 未绑定项目仅可提案 writer_create。确认时预留项目 UUID，创建后即使动作部分失败也绑定已存在项目。未知创建执行阻止第二次创建；刷新可补认原预留项目。
- 主任务审查提出执行提案中断恢复缺口，补充 `abandon_execution(thread_id, proposal_id)`；人工标未知、释放占用，不重放调用。晚到模型或动作结果不能覆盖未知终态。

## 实际改动

- `app/assistant_contracts.py`：有界输入、仅白名单动作、最多四项提案；复用 ProfileRef/EffortChoice。
- `app/assistant_schema.py`：threads/turns/proposals/executions 四表，项目线程唯一、请求键唯一、线程单运行 turn、复合归属外键。
- `migrations/versions/0013_assistant.py`：冻结表定义，无 app 导入；禁止历史删除、终态修改、已绑定项目换绑和提案参数覆盖；非空账本禁止降级。
- `app/assistant_service.py`：短事务预留、幂等重放冲突、上下文指纹检查、拒绝及确认、预留项目恢复、人工停止和安全错误文本。当前完整快照超过 24000 字符时拒绝模型调用，历史最近 20 条且整个 prompt 不超过 48000 字符；不截断当前权威上下文以允许写入。
- 模型原始 JSON 校验失败、未知动作及敏感配置值回显均不落为可执行提案，不回显原始提供方错误。只记录标准非负整数 token usage。

## 验证证据与局限

- 测试先建立缺失服务的 RED，并在隔离 PostgreSQL 中确认；执行恢复补充测试也先确认缺失 abandon_execution 的失败。
- 最终命令：`.venv/Scripts/python.exe -c "import os,pytest; from app.database import database_url; os.environ['TEST_DATABASE_URL']=database_url().set(database='postgres').render_as_string(hide_password=False); raise SystemExit(pytest.main(['tests/test_assistant.py','-q','-x','--tb=line']))"`。
- 结果：**16 passed, 1 warning in 27.78s**。warning 来自现有 Starlette TestClient 对 anyio 的已弃用别名。fixture 仅在 maintenance 连接创建随机 `fp_test_` 数据库，未改业务库；Windows 本地 PG 验证使用提权 PTY。故意采用简短 traceback 避免数据库连接参数进入失败详情。
- 覆盖：未绑定会话与项目恢复、幂等冲突、会话 OCC、脏草稿和上下文过期、拒绝无执行、无效/敏感模型输出、并发占用、并发接受仅调用一次、停止后晚到模型和动作、部分创建失败绑定、未知创建防重建、数据库历史保护、prompt 预算及迁移与 metadata 一致。
- 加测真实 AssistantActions 与 HTTP：未绑定对话创建提案→确认后实际建项目→人工确认剧本来源→建分镜→分镜修改提案→确认后实际修订分镜，已通过。另按 RED/GREEN 修复任意环境变量名指定的密钥回显保护。
- 所有模型提供方为可注入 fake；没有调用付费模型，没有验证真实模型效果。浏览器和既有全量回归由主任务整合验收。
- 最终整合审查按 RED/GREEN 修复项目身份预留竞态：创建动作刚插入项目但原会话尚未绑定时，另一标签页请求该项目会话应恢复预留动作的原会话，不能抢建第二会话导致唯一键冲突。仅改服务，无迁移变更；同一最终命令回归结果更新为 **17 passed, 1 warning in 25.16s**。

## 交接

- 以上六个代码/迁移/测试文件及本记录未暂存、未提交；按分工由主任务核对 diff 后阶段提交与推送。
- 已通知主任务 `register_assistant(Base.metadata)` 和 contracts/service 方法名；models 注册由主任务完成。
- 未修改其他任务足迹、博客或共享架构说明。未清理分支、工作树；未宣称已归档。

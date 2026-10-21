# 分镜工作台第一版

- 用户决定：先做分镜；已同意数据契约对齐、专业 Skill、生成/修改/确认/追溯闭环，保留通用模型 API 配置。
- 方向：复用当前未提交的 production 底座；在现有 `codex/database-foundation` 工作区增量实现，不另建丢失这些依赖的 checkout，不暂存其他任务文件。
- AI 实施取舍：文字分镜而非图片画板。单次文本规划生成完整候选，程序检查与人工确认；不追加隐式模型纠错或视频请求。
- 数据库：增加专用分镜运行记录。现有 generation_tasks 的 result_version_id 指向 script_versions，强行塞入分镜会破坏语义。运行记录保存输入摘要、固定配置/来源/Skill、状态、结果引用和用量。迁移只在临时库测试。
- 额度检查：本轮开始主要窗口剩余 90%，周窗口剩余 52%。账户共享；未购买或兑换额度。
- 当前状态：代码、文档、回归和审查已完成；保留当前分支的未提交改动。
- 验证计划：结构/来源与检查规则、HTTP 适配器、真实 PostgreSQL 幂等与失败/上游变更、真实浏览器修改和确认流程；模型以确定性替身测试，不冒称真实模型质量。
- 实际改动：contracts 增加生成输入/结构化台词/人物/创作补充；planning + K001/K002/K003 组成版本化提示词与规则提醒；chat 提供单次兼容接口；generation 提供预约、幂等、预算、来源重检和原子保存；schema/0006 增加分镜运行；store 抽出事务内分镜创建；API/main 接入执行与 /storyboard；新页面和编剧跳转；新增测试与工作台说明。
- 最终验证：`python -m scripts.test_local` 全量184 passed、0 skipped、1项既有Starlette/AnyIO弃用警告，121.90秒。最后的前端跨镜头输入恢复修复后，定向复跑 `test_storyboard_browser.py` + `test_writer_browser.py`：2 passed、0 skipped，同一警告，18.55秒；未因前端局部修复重复全量后端测试。Node展示单测6 passed；JS语法与git diff --check通过。所有数据库用例由fixture创建随机临时库并销毁，没有清空业务库。
- 红绿证据：缺失planning/chat模块、缺失页面先失败；同版本卡片变化采用、API仍显示不可执行、无效输入切镜丢失、第二镜无效输入刷新后首镜保存均先复现，再修复验证。
- 审查：requesting-code-review技能要求的只读子任务指出两项P2：busy禁用表单绕过校验，pending在终态/确定性拒绝后未清理；复核又指出恢复后未打开镜头的raw输入漏检。全部修复并加入真实浏览器回归，最终只读复核未发现新增P1/P2。审查者未独立跑通浏览器，浏览器实测证据来自主任务。
- UI检查：已查看真实Edge桌面截图。按叙事/空间/声音/帧设计折叠字段，减少长页；移动端390px自动断言无横向溢出。截图在忽略目录 `.runtime/storyboard-qa/`。
- 环境：沙箱首次连接本机5433被拒绝，授权复跑隔离库/浏览器后通过；没有用其他方式绕过。业务库未查询/升级。
- 相关文件：`app/production/{contracts,planning,chat,generation,store,schema,api}.py`、`app/production/skills/`、`app/static/storyboard.{html,css,js}`、`app/static/workbench.js`、`app/main.py`、`migrations/versions/0006_storyboard_runs.py`、`tests/test_storyboard_*.py`、`tests/storyboard-ux.test.cjs`、`docs/storyboard-workbench.md`、本轮spec/plan；README、底座说明、技能蓝图增加当前实现状态。
- 提交/合并：本轮无提交、推送或合并；已有writer提交5534950保持。未暂存他人工作，未清理任何分支/worktree。资料库和production前轮改动也仍在当前工作区，不能把未提交状态写成已归档。
- 局限与下一步：启用业务库前按既有数据库说明备份并显式迁移0005/0006，然后重启应用，在 `/storyboard` 配置文本模型、用真实已确认剧本做人工标注评测。真实模型效果、网关差异、专业24案例未跑；图像/视频执行、资产服务、多章节工作台、后台队列不在本轮范围。无当前开发阻塞。
- 收尾额度复核：主要窗口剩余78%、周窗口50%，账户共享；未兑换/购买额度。

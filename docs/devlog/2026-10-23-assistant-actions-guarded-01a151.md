# 助手封闭业务动作与保存状态上下文

## 需求与决定

- 用户需求由主任务分解：助手提议既有编剧、分镜、素材与后期动作，执行仍走既有服务；人工确认剧本/分镜、人工媒体审阅、成片验收不在助手动作白名单内。
- 本任务独占 `app/assistant_actions.py`、`tests/test_assistant_actions.py`，并为主任务执行账本提供 `StoryService.create(..., project_id=...)` 内部预留编号接口。公开 CreateProject 契约不增加编号字段。
- 预留编号严格要求32位小写UUID十六进制，仍使用 StoryService 原有单进程锁；发现已存在的预留项目仅返回保存状态，防止未知结果后重复新建。
- 提案参数直接复用既有 Pydantic 请求模型，只有 storyboard_id/run_id 为封闭路由字段；版本、来源和暂停编号固定到保存状态，调用方显式提供过期版本时拒绝。模型调用与数据库业务写入交由既有服务执行。

## 实际改动

- 13项封闭动作：writer_create/choose/revise/clarify、storyboard_generate/revise/review、image_generate/select、video_select/inspect、timeline_save、export_create。
- 按工作台阶段提供真实参数 JSON Schema（含嵌套定义）和紧凑能力说明；分镜和时间线修订以既有完整内容契约生成字段前后差异，不引入自由补丁语言。
- 上下文包含当前项目保存正文、版本、暂停节点、选中分镜/镜头、素材元数据和当前时间线；模型配置只提供用途、模型、适配器、版本与是否配置，排除密钥引用、服务地址和私有存储路径。
- fingerprint 根据权威保存数据、版本、选择和配置摘要计算；长内容裁剪后仍保留原始权威摘要，并明确标记上下文不完整。上下文对齐主服务24,000字符限制；有裁剪时提案禁止执行。
- 不将图片、视频元数据描述为已观察到真实内容；抽帧调用既有 InspectionService，只获得技术证据，不代替语义或音频审查。
- 预览阶段不写业务库、不调用模型；缺配置或缺用户确认显示不可执行原因。

## 资料使用边界

实际阅读本地 `docs/knowledge/aigc-video/README.md`、`maintenance.md`、`app/production/planning.py` 的 `build_packet`/`review_board`，以及既有生产服务契约。这里只复用项目已经实现的来源版本、语义审查边界和 K001—K003 入口；本任务未新增外部提示词采纳、未声称精读未读取的固定上游来源，未验证真实图像或视频模型效果。

## 验证与阶段状态

- 测试先行；首次运行在模块不存在时失败。初版9项 PostgreSQL测试通过；新增边界测试先暴露路由字段绕过、时间线素材范围遗漏与上下文长度问题，随后修正。
- 测试数据库使用现有 `tests/conftest.py` 的随机 `fp_test_<uuid>` 临时库。开始命令缺 TEST_DATABASE_URL 时只跳过，沙箱网络限制导致本机连接失败；允许本机PG测试后执行真实隔离库测试。后续命令显式将本机连接的管理库切换为 `postgres`，没有清理业务库。
- 当前代码与记录由主任务集中整合、核对并提交；本任务不独立提交共享工作目录。完整末轮结果由后续追加记录。
- 真实付费模型、真实视频生成与画面语义效果未运行。执行幂等和并发账本由主任务的 AssistantService 测试负责，动作层只将业务幂等键传入既有服务。

### 最后一轮验证

- `tests/test_assistant_actions.py`（17项）、`tests/test_story.py` 和 `tests/test_free_creation.py` 合计 **30 passed**；已有 Starlette/AnyIO 弃用提示1条。使用本机 `postgres` 管理连接与随机测试库，未调用付费模型。
- 新增实际媒体流程：替身图片供应商返回真实PNG，经现有媒体服务入队、解码保存后由助手选用；本地真实小视频经既有视频验证后由助手选用、抽帧，报告仍为 `pending` 且语义审查 `not_configured`；既有视频素材保存时间线并排队导出，`accepted` 保持false。
- `git diff --check`（本任务文件）与 `compileall` 通过。业务动作实现稳定，主任务负责HTTP、UI、迁移和完整集成回归；本任务未提交或推送，等待主任务集中归档。

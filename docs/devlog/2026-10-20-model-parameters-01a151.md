# 模型型号与思考参数适配设计

- 用户需求：不同模型型号、思考等级等参数可选择并正确适配。用户已选首批范围“通用兼容接口和DeepSeek，其他后续扩展”。
- 当前代码核对：ModelConfig已有自由填写model、地址和密钥环境引用；GenerationParameters仅temperature/max_tokens/seed；网页不暴露高级参数，ChatPlanner固定Chat Completions并默认temperature0.2/max_tokens12000。旧编剧DeepSeekProvider仍为独立环境变量/LangChain路径。
- 使用brainstorming技能，当前为设计阶段，未改业务代码、配置或数据库，未调用真实模型。正在形成可核对方案，待用户确认后进入实施。
- 已读官方来源（2026-10-20）：https://api-docs.deepseek.com/guides/thinking_mode/ 与 https://api-docs.deepseek.com/api/list-models/ 。官方当前描述thinking开关与reasoning_effort分开、模型目录可含effort和协议能力；思考模式下temperature可能被忽略。只采用上述官方规范，未验证用户具体网关支持情况，不写死所有模型型号或宣称兼容所有平台。
- 候选方案：仅参数透传（易静默无效）；通用参数+供应商规则（建议）；为每家实现独立完整调用链（当前维护成本高）。
- 建议：通用Chat协议保留、补DeepSeek参数规则；模型列表显式刷新+手填回退；按模型能力显示选项，无能力信息不自动猜测思考等级；保存固定配置版本并记录实际发送参数；编剧接入同一配置层须兼容旧项目默认行为，不改历史用量/重试/预算。
- 待确认：整体实施方案（包括旧编剧统一配置的分阶段接入顺序），设计文档后续落盘。未暂存/提交；前轮业务库已升0007不代表本功能已实现。

- 已形成待确认方案docs/superpowers/specs/2026-10-20-model-parameters-01a151.md，复核了范围、默认行为、未知能力和真实验证边界。来源list-models直接open一次超时，实施前需完整再核对，不能只凭检索片段实现完整协议。无业务代码/数据库改动。

## 用户修订与实施

- 用户收敛为输入区附近仅“型号、思考等级”，不增加高级参数面板；按此调整设计并开始实施，不再次申请相同范围确认。
- 使用writing-plans、TDD与frontend-design，按现有纸色/绿色工作台做紧凑控件；实施顺序见本轮plan。共享工作树原地实施，前轮底座尚未提交不另开丢失依赖checkout。
- 首段分镜/文字审核；编剧共享配置后续接入如先前设计阶段约定。模型目录仅配置列表，远端发现从本段移出。配置JSONB和manifest可承载，无迁移业务库。
- 阶段额度主要77%、周41%；无购买/兑换。

## 实际实现与中途验证

- 新增app/production/reasoning.py受控编译器、ModelConfig协议/声明档位及请求reasoning_effort。通用旧请求保留temperature/max_tokens；effort改max_completion_tokens；DeepSeek按thinking+reasoning_effort转译，明确区分默认与关闭。
- 生成与审核在预约前校验等级，在已有manifest记录实际参数/规则版本。默认字段从幂等身份序列省略，旧客户端重放不因新字段变为另一次调用；换档位同键409。没有新增数据库表或迁移。
- 新增model-picker.js复用紧凑控件，集成到storyboard.js及storyboard-review.js；模型ID/配置名/版本显示，可按配置规则联动档位与记忆选择，pending冻结并恢复原等级。配置区新增协议规则，下游没有高级参数面板。
- RED：test_model_reasoning.py先因reasoning模块不存在失败；实现后与原契约37 passed。API/适配相关45 passed。浏览器新增断言先因缺#effort失败，UI实现后1 pytest（实际2个Node端到端流程）通过。
- 第一次综合受影响回归93 passed /0 skipped/1既有Starlette弃用警告，43.76s；含真实随机PG库与浏览器、模型使用确定性替身/MockTransport，不算真实模型兼容验证。
- 按requesting-code-review技能派只读代理reasoning_picker_review复核，发现P2：default未清除配置保存的high。新增回归先失败，修复choose_effort默认清空覆盖后12单元passed。其余未发现具体重要问题。最后94项回归运行中，结果待补。
- OpenAI Docs技能用于核对effort接口的max_completion_tokens等字段，实际打开官方https://developers.openai.com/api/reference/resources/chat；DeepSeek按已读官方thinking_mode。不推荐或硬编码具体最新型号。
- 手工查看真实浏览器截图model-picker-desktop.png；两项紧凑条可读。修正原secondary悬停暗底暗字问题，维持原纸色/绿色风格。移动端无横向溢出。
- 当前编剧未接新型号/等级控件，按分阶段范围如实保留；本轮不调用模型、不改业务数据、不迁移业务库、不暂存/提交其他任务改动。

## 收尾

- 修复审查问题后，最后一轮8个相关测试文件：94 passed /0 skipped/1既有Starlette-AnyIO弃用警告，51.16s。覆盖原配置/分镜/审核行为及新增参数适配、默认清覆盖、幂等、实际请求体、浏览器两条端到端流程与Alembic schema一致性。
- Python编译、三个前端脚本node --check、git diff --check通过；只有已有LF/CRLF提示。不是整个仓库全量重跑，不与上轮213项合并计数。
- 核心改动：新增reasoning.py、model-picker.js、test_model_reasoning.py；扩展contracts/review_contracts、chat/store/generation/reviews；storyboard.html/css/js及storyboard-review.js；扩展generation/reviews和浏览器回归；更新本轮spec/plan及storyboard-workbench文档。
- 截图保留在.runtime/storyboard-review-qa/model-picker-desktop.png及desktop/mobile.png。确定性模型测试而非真实模型示例，未写业务数据。配置能力来自声明而非自动探测，尚未用实际网关验证。
- 用户最后范围已完成：分镜与文字审核为型号/思考两个紧凑项；不提供高级参数面板/远端型号发现。旧编剧共享配置接入待后续，现有API和密钥默认保持。
- 存储复用既有JSONB与manifest，本轮无需新迁移，业务库仍0007；原工作树保留、未暂存/提交/合并，无清理分支或worktree。后续可配置真实模型做显式效果验证。

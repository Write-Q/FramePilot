# 文字分镜审核质量收尾

- 用户决定：按审核质量、参考图/首帧、单镜视频、批量与后期顺序推进；本轮先做第一步。
- 已核对：review_prompt/reviews/chat、现有审核1.0.0规则、2026-10-20真实评测与测试。无业务文件预先修改；保留其他任务未跟踪文件。
- 原因：规则未明确时间余量与已披露假设的误报边界；ChatPlanner把length和其他非法输出都归为invalid_output。
- AI方案：规则升级1.1.0，保留旧文件和原结果；精简重复问题但不设会漏掉重要问题的硬条数上限；输出截断独立错误码且不自动重试。先补控制案例再评估low档，不静默改变用户参数。
- 不采用直接增大所有请求预算或强制关闭思考：未有对照证据，可能增加成本或改变用户选择。
- 来源：本次新增规则来自项目失败案例与现有契约；外部来源定位沿用已采用清单，本轮未重新读取或新增借鉴外部材料。
- 额度检查：主窗口剩余75%，周窗口90%；账户共享。模型API账单未知。
- 未完成：实现、回归与真实对照、默认参数结论；后续媒体功能尚未开始。未提交、推送或改业务库。

## 实施与验证结果

- 新增审核1.1.0规则，保留1.0.0原文件；更新注册哈希和workflow版本。明确时间余量、已披露假设、具体制作后果与同根因合并规则。没有代码硬过滤审核问题。
- ChatPlanner识别finish_reason=length为output_truncated，保留usage；即使残余JSON合法也拒收。界面沿用error展示，提供手动降档/调整预算提示，不自动重试。无需数据库迁移。
- RED：两个截断测试先失败，实际invalid_output与预期output_truncated不符；修复后通过。增加审核API失败落库、usage、提示、幂等不重复调用验证。
- 首次部分测试30 passed/16 skipped/1 error，error为沙箱临时目录创建权限。之后无DB的筛选运行29 passed/5 skipped/14 deselected，不视为完整回归。数据库首次回归因Docker未运行中止，不计通过。
- 沙箱内Explorer未创建Docker进程；正常桌面权限下同一Explorer入口成功恢复framepilot-db-1 healthy。未直接启动Docker主程序、删除socket、重置或修改卷。
- 最后完整受影响回归：60 passed/0 skipped/1既有Starlette-AnyIO弃用警告，24.41秒。覆盖生成/审核API、契约、规则防损坏、模型参数及控制案例；使用随机临时PG库与模型替身。未重跑全仓、未单独重跑浏览器，前端无改动。git diff --check通过（既有换行提示）。
- 真实控制：deepseek-flash目录可用，low/12000预算，4次有效报告，10848 tokens/15.078秒，无重试。时间余量与已披露假设2例无目标误报，道具归属/首帧矛盾2例准确定位。原始最终JSON与报告在docs/qa/review-controls-20261022-01a151/；不保存思考或密钥，不写业务库。
- 本任务AI判读，非专家盲审；ownership有姓名笔误和备选修订范围偏宽。没有旧新提示词或高低档配对，不能宣称整体准确率提高或low普遍优于high。
- 决策：low可作为短分镜试用建议，保持产品default语义与用户配置不变。长分镜、跨场连续性、建议忠实度待扩大验证。短案例质量检查点完成，下一步进入参考图/首帧模块，尚未实现生图/视频。
- 改动文件：app/production/chat.py、generation.py、review_prompt.py、skills/review_registry.json及新增storyboard-review-1.1.0.md；tests/test_storyboard_generation.py、test_storyboard_review_contracts.py、test_storyboard_reviews.py及新增test_review_controls.py；新增scripts/evaluate_review_controls.py；工作台文档、本轮计划与QA记录。
- 未提交、推送或合并。其他任务未跟踪记录与学习文档原样保留；没有清理任何分支、工作树或非本轮临时数据库。

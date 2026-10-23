# 审核质量收尾实施计划

目标：先处理已观察到的审核误报与截断诊断，再用明确正负例验证，作为视觉生成前的检查点。

架构：保留报告契约与版本绑定；新审核提示词及注册哈希作为独立1.1.0版本。ChatPlanner仅新增length错误分类，generation.ERRORS统一向界面返回可操作提示，不自动重试或改变参数。无需数据库迁移。

- [x] 在tests/test_storyboard_generation.py加入length（含合法残余JSON）拒收、usage保留、单次请求断言，先运行失败，再修复chat.py与generation.py。
- [x] 新建storyboard-review-1.1.0.md：明确时间余量、未知时长、已披露假设、缺信息与实际冲突边界；更新review_registry.json和review_prompt版本。旧规则保持可追溯。
- [x] 更新审核包版本与防损坏测试；构造正常时间余量、首帧提前完成动作、道具归属冲突、已披露空间假设四个合成控制案例，验证契约及固定输入。
- [x] 跑针对性测试和真实模型控制组（最多四次，单次12000输出预算，不重试；遇认证/限流/连接故障停止）；记录使用档位、token、失败和人工判读。模型名称只使用可用配置/目录，密钥和思考过程不落盘。
- [x] 在足迹与QA报告记录结果与下一步；语义效果不足则不宣称第一步已完成，不提前强制新默认档位。

验证命令：.venv/Scripts/python.exe -m pytest tests/test_storyboard_generation.py tests/test_storyboard_review_contracts.py tests/test_storyboard_reviews.py tests/test_model_reasoning.py；数据库部分通过现有隔离fixture，不能以跳过冒充通过。

控制案例调整：源码核对表明节拍超时已由Shot契约拒绝，无法作为有效审核输入；改用契约允许、语义错误的首帧冲突。

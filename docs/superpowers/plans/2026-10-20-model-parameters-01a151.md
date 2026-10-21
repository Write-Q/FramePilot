# 模型号与思考等级 Implementation Plan

**Goal:** 分镜和文字审核仅增加紧凑型号/思考等级，接口规则在配置区维护。
**Architecture:** ModelConfig增向后兼容协议及声明档位；请求增effort，适配层生成受控请求体；manifest保存实际参数和规则版本。保留旧默认幂等指纹。无新迁移。
**Tech Stack:** Pydantic/httpx/FastAPI/SQLAlchemy/原生JS/Playwright。

- [x] tests/test_model_reasoning.py先测payload转换、旧默认、非法档位与旧幂等序列；观察失败后新增reasoning.py并扩展契约。
- [x] ChatPlanner使用body构建器，生成/审核预约前验证effort、manifest固定实际参数；profiles返回声明档位。回归原生成/审核。
- [x] 浏览器添加型号+思考等级联动断言，先看到缺UI失败；实现复用model-picker.js和紧凑样式，生成/审核pending恢复原选择，禁用时不丢选择。
- [x] 隔离集成验证实际provider配置与manifest/幂等，浏览器桌面移动端；必要回归、代码审查、文档记录。业务库不写测试数据，不真实模型调用。

具体契约：request.reasoning_effort默认default；ModelConfig.reasoning_protocol默认none、可选effort/deepseek；GenerationParameters.reasoning_effort默认为null。none仅default；effort默认支持low/medium/high；deepseek支持none/low/high/max。可通过reasoning_levels声明子集，不允许越出协议集合。默认不发送reasoning字段；DSnone发送thinking.disabled；DS非默认其他发送thinking.enabled及reasoning_effort；effort发送reasoning_effort和max_completion_tokens，跳过默认temperature。显式不兼容采样参数拒绝并提示，不自动忽略。

测试命令：.venv/Scripts/python.exe -m pytest tests/test_model_reasoning.py -q -p no:cacheprovider；隔离DB配置按既有scripts.test_local。工作区依赖未提交前轮底座，原地实施，不批量暂存、不创建丢失依赖worktree。

最终验证94 passed，范围与局限见本轮足迹。未提交/合并，保留现有共享工作树；未对业务库或真实模型发起写入/调用。

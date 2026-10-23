# 后期真实浏览器验收（7b2e）

- 任务：补齐本地选片 → UI 裁切/字幕/WAV 音轨 → 保存/排队 → 默认 FFmpeg 导出 → 原生播放器推进 → 浏览器下载 → 人工验收持久化的可重复验收。
- 范围：仅本任务的 `tests/test_editing_browser.py`、`tests/editing-real-playback.cjs` 及本记录；不修改应用或共享说明，不自行提交，由整合任务统一归档。
- 决策：复用既有 `editing` fixture 的实际 H.264 素材与随机临时 PostgreSQL 库；浏览器只通过真实 UI 写入，文件信号仅同步测试运行器与独立默认渲染器。故事模型与上游生成适配器是显式测试替身，没有付费模型调用，不代表模型生成质量。
- 验收设计：浏览器实际 WAV 上传和保存请求；原生 video readyState、分辨率、时长、play()/currentTime；Range 字节与下载附件头；点击下载所得文件逐字节比较；页面重载后选项及验收仍在，Python 独立读取数据库验证。进一步解码成片，检查字幕阶段的实际像素对比与非静音 AAC 样本。
- 验证结果：2026-10-23 使用本机 Edge、项目 `.venv`、随运行时提供的 Node/Playwright 执行 `pytest -q --tb=short tests/test_editing_browser.py`：**1 passed, 1 warning in 10.97s**。警告来自既有 Starlette/AnyIO 的 BlockingPortal 弃用提示。
- 运行配置：在 Python 进程内通过 `app.database.database_url().set(database='postgres')` 派生 `TEST_DATABASE_URL`，不输出凭据。测试数据库由 `tests/conftest.py` 创建与删除，仅使用维护库连接创建随机 `fp_test_` 库，未对业务库写入。Node 路径通过 `FRAMEPILOT_NODE`、依赖目录通过 `NODE_PATH`、Edge 路径通过 `FRAMEPILOT_CHROME` 注入，没有把本机专有路径写进测试。
- 排查记录：沙箱首次阻止本机 PostgreSQL TCP 访问，提升执行经审核允许后测试正常连接。第一次提升运行的 UI、渲染、下载、数据库检查均通过，最后新增音频断言因测试环境没有 NumPy 失败；已改用 PyAV 重采样与标准库 PCM 样本解码，最终完整重跑通过，没有增加 NumPy 依赖。
- 验证边界：这里验证自动化操作“记录人工验收”入口后的持久化，不等于真人实际审片。素材为本地编码灰色视频与合成正弦音频；字幕像素对比证明实际烧录，非静音解码样本证明实际混音，不证明真实模型效果、主观观感或设备扬声器音质。
- 未完成事项：本任务范围内无；整合任务仍需纳入统一阶段验证、提交与推送。
- 提交/合并状态：未提交，交整合任务处理。

# FramePilot：故事、分镜与视频制作工作台

本地单用户学习项目：FastAPI + Pydantic + LangGraph + LangChain/DeepSeek + PostgreSQL。
协作创作、自由编剧、十维概括、审核建议、人工确认和版本追溯已接通。
已实现分镜、图片/视频持久化任务与本地后期成片；尚未接入真实图片/视频供应商，RAG和多用户认证尚未实现。

第二版新增[分镜工作台](docs/storyboard-workbench.md)：已确认剧本 → 通用文本 API 生成文字分镜 → 逐镜编辑 → 版本保存与人工确认。支持独立文字审核、型号与思考等级选择、专业规则提醒、生成追溯和重复请求保护。图片阶段现有[静态帧制作、视频任务底座、播放与选用](docs/shot-media.md)，需显式迁移至0012并单独启动图片worker。尚未选定真实图像/视频供应商，媒体效果未验证；[文字模型评测](docs/qa/storyboard-real-20261020-01a151/report.md)与[审核控制组](docs/qa/review-controls-20261022-01a151/report.md)单独记录。现有编剧模型配置保持原样。

视频审核第一版提供[技术报告、真实帧证据及人工时间段记录](docs/video-inspection.md)；没有接入自动多模态内容审核，人工记录不自动选用视频。

新增[本地后期成片第一版](docs/postproduction.md)：时间线版本、裁切排序、WAV音轨、字幕和独立FFmpeg导出队列。支持独立本地视频上传、明确加入时间线和成片验收，需单独启动本地导出worker。业务库已升级0012，具体边界及证据见[接入前验收说明](docs/pre-model-readiness.md)。

研发参考统一从[AIGC 视频资料库](docs/knowledge/aigc-video/README.md)进入：按制作领域、开发问题和来源编号定位专业知识、官方接口、参考实现与评测案例，减少重复广域搜索。

编剧与文字游戏的整合范围、验证结果和未完成事项见 [整合版收尾说明](docs/writer-game-release.md)。

## 首次安装与启动

需要 Python 3.12、Docker Desktop（或自行准备 PostgreSQL）。在项目目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
Copy-Item .env.example .env
```

编辑 `.env`：设置随机 `POSTGRES_PASSWORD` 并同步更新 `DATABASE_URL`；填写 `DEEPSEEK_API_KEY`，也可继续使用系统环境变量。已有 `.env` 时不要用模板覆盖。

```powershell
docker compose up -d --wait db
.\.venv\Scripts\python.exe -m scripts.init_db
.\start.ps1
```

工作台：http://127.0.0.1:8000/ ；离线 Swagger：http://127.0.0.1:8000/docs 。
后续使用时确保数据库容器运行，再执行 `start.ps1`。表结构升级显式运行 `scripts.init_db`，应用启动不自动建表。
数据库端口只绑定本机 `127.0.0.1:5433`，数据保存在 Docker 命名卷。`docker compose down` 不删除卷；不要对有数据的实例使用 `down -v`。

当前仍只支持单个应用进程，不使用多个 workers；换数据库没有同时完成多用户并发改造。

## 当前功能

- 互动故事：`/play` 提供三种背景开局、主角行动、轻量随机判定、死亡规则、存档和回溯分支；可配置参考图生图网关，详见 [互动故事说明](docs/story-game.md)。真实生图质量需配置后验证。

- 协作模式：完整故事直接审核；标题/片段先提取、提出候选方向，用户选择后写稿。
- 自由编剧：构思 → 编写 → 审核 → 有限自动修订，需要用户或达到限制时暂停。
- 原稿直接制作：零模型调用保留原稿并导出交接文件，尚未接视频平台。
- 审核问题关联十维卡片；可采用建议、用用户方案替换或解释为何保留。
- 仅澄清只复审，不改正文；确认时接受现状与采用修改建议是不同操作。
- 查看历史版本、正文差异、决策记录，导出 Markdown；失败时手动重试失败节点。
- SSE 展示阶段和未校验的生成预览；最后通过结构与引用检查才保存正式结果。

每个项目最多 3 次正文修订、10 次模型请求；失败请求及澄清也占额度。停止或重启不会清零。
真实模型质量仍需标注评测；引用存在不等于模型判断正确。详见 [编剧模块说明](docs/writer-module.md)。

## 数据存储

业务表使用 SQLAlchemy，表结构通过 Alembic 管理：

| 表 | 职责 |
| --- | --- |
| fp_projects | 当前状态与暂停信息 JSONB、额度、创建时间 |
| fp_versions | 不可覆盖的正文版本和十维卡片 |
| fp_calls | 持久化模型调用账本与 token 用量 |
| checkpoints / checkpoint_blobs / checkpoint_writes | LangGraph 执行检查点，由 PostgresSaver 管理 |

业务和检查点使用同一个 PostgreSQL 数据库中的独立表与连接池。预占调用额度时锁住项目行，事务提交后才发模型请求。
正常暂停支持重启恢复；进程在执行中突然退出仍不具备可靠后台队列的自动恢复能力。

## 从旧 SQLite 迁移

先停止旧应用并确认没有执行中的项目。准备**空的 PostgreSQL 目标库**，设置 `DATABASE_URL` 并初始化，然后执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-migration.txt
.\.venv\Scripts\python.exe -m scripts.init_db
.\.venv\Scripts\python.exe -m scripts.migrate_sqlite --source data --confirm-stopped
```

工具用 SQLite backup API 创建含 WAL 的一致性备份，再在一个 PostgreSQL 事务中导入项目、版本、账本和全部检查点，核验后提交。拒绝覆盖非空库；失败整体回滚，原文件不删除。双库备份要求先停服。
迁移后 `FRAMEPILOT_DATA_DIR` 不再作为运行配置；`data/` 仅保留旧数据和备份。详见 [数据库迁移说明](docs/postgresql.md)。

## 测试与阅读

完整测试需要真实 PostgreSQL、可创建临时数据库的测试账号，以及迁移测试依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-migration.txt
# 本地学习环境可复用 DATABASE_URL 的服务器，但测试会创建独立随机库。
.\.venv\Scripts\python.exe -m scripts.test_local
```

`scripts.test_local` 使用 `TEST_DATABASE_URL`，未配置时显式选用本机配置；拒绝非本机自动回退。
每个数据库用例独立创建 `fp_test_<随机编号>`，结束只删除自己创建的库。模型使用替身，不产生 API 费用。
直接运行 pytest 而未配置 `TEST_DATABASE_URL` 时数据库测试会跳过，不代表数据库迁移验收通过。

可选的真实浏览器回归使用独立测试数据库和模型替身，覆盖意见隔离、刷新/重新载入、提交后草稿失效、桌面及手机操作提示。需要 Node.js、Playwright 和 Chromium；未安装时会明确跳过这一项。可将测试依赖装在忽略目录中：

```powershell
npm install --prefix .runtime/browser-tests playwright
node .runtime/browser-tests/node_modules/playwright/cli.js install chromium
$env:NODE_PATH = (Resolve-Path .runtime/browser-tests/node_modules).Path
.\.venv\Scripts\python.exe -m scripts.test_local
```

如需使用已有 Chromium，可设置 `FRAMEPILOT_CHROME` 为可执行文件路径；`FRAMEPILOT_UI_ARTIFACTS` 可指定浏览器截图输出目录。

阅读顺序：`domain.py → workflow.py → service.py → models.py/storage.py → provider.py → main.py`。
字段与关键函数已补充中文注释。[架构记录](docs/architecture.md)保留历史阶段，数据库部分以本页和迁移说明为准。

可选的 `scripts/smoke_deepseek.py` 会真实调用 DeepSeek，使用独立 `SMOKE_DATABASE_URL`，最多两次请求；不是质量评测。本轮迁移没有执行该付费脚本。
`.env`、`data/`、`.runtime/` 不进入 Git；连接密码和故事数据不要提交到仓库。

# FramePilot：故事创作与审核最小闭环

本地单用户学习版。DeepSeek 负责提取、修订与审核；LangGraph 编排循环、暂停和确认；SQLite 保存故事版本、执行检查点与模型请求账本。当前没有视频生成、RAG 或外观一致性检查。

## 启动

在项目文件夹的 PowerShell 终端运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 使用工作台，或 http://127.0.0.1:8000/docs 使用离线 Swagger。停止服务按 Ctrl+C。请保持单个进程，不使用 `--workers`，不要将这个无账号认证的学习版直接开放到公网。

## 环境配置

从进程环境读取 `DEEPSEEK_API_KEY`，也支持在项目根目录创建 `.env`。只在本机填写，不提交密钥。可参考 `.env.example`，可选项为 `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`，默认官方地址与 deepseek-chat。

重新部署可用 Python 3.12 创建虚拟环境，然后 `python -m pip install -r requirements-lock.txt`。当前机器的环境已经安装完成。

## 如何使用

1. 输入故事和创作模式，可补充不可改变的要求。
2. 提交后等待提取及审核。每次真实模型请求都可能产生费用。
3. 观察十维卡片的信息来源及原文证据；审核意见是疑点，不是绝对裁决。
4. 需要修改时填写具体要求，点击“提交修订并重新审核”。修订自动形成新版本。
5. 无待处理问题时确认版本；有建议性问题时逐项勾选接受。约束冲突或需要澄清的问题必须先修订。
6. 复制项目编号以便以后载入。工作台会在当前浏览器记住最后一个编号；故事内容保存在本机数据库，不在浏览器中。

## 本版边界

- faithful（忠于原稿）与 collaborative（协作创作）遇到问题均先暂停。两者共享路由，提示词对允许改写范围有不同要求；当前没有独立的多选创意提案页面。
- free（自由发挥）可对无需用户决策的问题自动修订；涉及约束或用户选择则暂停。
- 每个项目累计最多 3 轮修订、10 次模型请求，人工恢复不会刷新额度。修订前预留至少两次额度用于修订和重新审核。
- 超限保留草稿和未解决问题，不伪装为通过。当前不能给已有项目增加额度，也没有自动重试；需要重新规划时可复制草稿创建新项目，这是新的计费任务。
- 请求数上限不是金额预算；调用账本记录供应商返回的 token 使用量，但不计算费用。
- API 创建/修订会同步等待图运行到暂停或结束；页面期间显示等待状态。尚未实现后台队列和流式节点进度。
- 常规人工暂停支持重启恢复。执行过程中突然终止不自动重放模型请求；现有快照可能显示 running，需要检查执行检查点，当前尚未提供失败任务自动恢复入口。
- 理解卡片目前每个维度是文本及来源，不是完整的稳定实体编号与事件状态数据库；初版审核依靠原文和卡片，不宣称已实现严格的时空状态推理。
- 证据位置匹配只能排除不存在的引用，不能证明 AI 的解释正确。需用人工标注案例继续评估漏报和误报。

## 代码怎么读

按 `domain.py → workflow.py → service.py → storage.py → provider.py → main.py` 阅读，配合 `docs/architecture.md`。

| 文件 | 职责 |
| --- | --- |
| app/domain.py | 输入输出的业务数据约定 |
| app/workflow.py | 提取、审核、路由、修订、人工暂停 |
| app/service.py | 创建和恢复、版本校验、确认权限 |
| app/storage.py | 业务快照、不可变剧本版本、模型调用记录 |
| app/provider.py | DeepSeek 通信及安全错误输出 |
| app/prompts.py | 分任务提示词及版本号 |
| app/main.py | FastAPI 入口和工作台资源 |

## 测试与真实调用

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

自动化测试使用模型替身，不收费。验证模式边界、循环上限、重启恢复、错误响应、证据来源和 API。

```powershell
.\.venv\Scripts\python.exe scripts\smoke_deepseek.py
```

这个命令会真实调用 DeepSeek 最多两次，使用固定虚构短故事，结果保存在 data/smoke。它是连接与结构验证，不是质量评测。

`data/`、`.env`、`.runtime/` 不进入 Git。保留数据库才能继续已有项目。复制项目到其他机器时，虚拟环境应重新创建。

## LangChain 接入版

模型层现使用 `ChatPromptTemplate → ChatDeepSeek.with_structured_output → 业务校验`；LangGraph 管理审核与人工暂停。详见 [架构说明](docs/architecture.md)。当前持久化仍为 SQLite，岗位导向的其他组件按后续业务阶段落地。依赖变更后重新安装 requirements.txt 并重启服务。

## 编剧模块新版

已接通协作选方向、逐条采用/替换建议、仅澄清复审、原稿零调用交接、决策历史、正文差异、导出和手动失败重试。使用方式及未完成的外部联调边界见 [编剧模块说明](docs/writer-module.md)。

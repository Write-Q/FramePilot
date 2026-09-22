# FramePilot 模拟视频接口实施计划

**Goal:** 无 API 密钥也可体验创建任务、查询状态、获取模拟结果。
**Architecture:** FastAPI 提供三个接口，内存保存任务。后台协程驱动 queued → running → succeeded/failed；关闭服务时取消未完成任务。结果返回明确标注的公开示例地址，不声称生成了视频。
**Tech Stack:** Python、FastAPI、Uvicorn、pytest、httpx。

- [x] 编写 tests/test_api.py：验证成功和失败流程、未就绪结果、未知编号、空描述。
- [x] 运行测试，确认接口未实现导致失败。
- [x] 编写 app/main.py：请求校验、任务模型、后台模拟、三个路由和生命周期清理。
- [x] 运行全部测试，再启动真实服务验证 HTTP 流程。
- [x] 提供依赖版本、启动脚本、中文 README 和一个修改练习。

文件职责：app/main.py 为最小后端；tests/test_api.py 为接口验收；start.ps1 为本地启动入口；README.md 为学习和试用说明。当前目录无现存代码仓库，直接在已授权工作目录开发。


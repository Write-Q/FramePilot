# Docker Desktop 启动失败排查

- 用户反馈：每次由本任务启动 Docker 都弹出意外错误，要求检查。
- 只读证据：Docker Desktop 4.89.0.238018；宿主日志2026-10-20T02:31:50Z记录Ingest监听初始化失败，rename sailor-ingest.sock→.stale返回文件不可访问。原对象创建于10月19日09:36，0字节ReparsePoint。fsutil只读查询返回1920；run父目录ACL给用户完全控制。
- 环境：CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY=OpenAI.Codex_2p2nqsd0c76g0。尚不能仅凭此证明本机故障完全由MSIX虚拟化引起。
- 参考已读：https://github.com/openai/codex/issues/52698 ，报告同款Docker版本与MSIX AppData下AF_UNIX错误1920，提出从explorer启动；这是用户报告及实验结论，不是本机已验证修复。
- 决策：先退出失败实例，再从桌面explorer启动对照验证。不删除socket、不重命名runtime目录、不修改ACL、不reset/prune/unregister、不动数据卷。
- 当前：等待关闭命令；尚未验证恢复。分镜审核开发中途受此影响，集成测试6项连接超时，不计为功能通过。

## 对照验证与结果

- 自带 docker desktop stop --timeout 20 未能结束崩溃实例；随后只停止已核实安装目录下的Docker Desktop/com.docker.backend进程。
- 经 Windows explorer.exe 启动原安装可执行文件；不修改任何Docker文件。提升权限只读 docker version 成功返回Server29.7.2；docker ps 显示framepilot-db-1 healthy，5433端口恢复；另有promptstudio-pg按既有策略启动。
- 同一版本、未处理socket、仅改变启动上下文后恢复，支持Codex/MSIX启动环境为本次触发条件。不是Docker版本缺陷已永久修复的证明。未做停启循环验证，避免影响其他项目运行。
- 后续约定：由Codex恢复Docker时先只读检查；缺引擎时通过explorer桌面入口启动，不直接Start-Process Docker可执行文件。如失败先读日志，不循环重启、不自动清理runtime。
- FramePilot隔离库回归恢复：审核集成6项+Alembic schema一致性1项，共7 passed。业务库未迁移，数据卷未改动、未reset/prune/WSL注销。记录未提交。

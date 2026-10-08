---
{"title":"FramePilot 开发手记 06：Docker 启动失败，先定位通信文件","description":"一次残留套接字导致的 Docker Desktop 启动故障：保留数据卷，验证恢复，再继续数据库验收。","date":"2026-09-23","tags":["FramePilot","Docker","故障复盘"],"slug":"framepilot-06-docker-recovery","draft":true}
---

> 本文复盘本机一次 Docker Desktop 启动故障，整理于 2026-09-24。下述处理基于当时的日志与目录检查，不应作为所有 Docker 启动错误的通用清理步骤。

## 最先看到的是数据库连接失败

PostgreSQL 迁移已经完成，准备补做验收时，测试却一直等连接。检查 Docker 后发现引擎没有运行，启动后弹出异常窗口。

窗口中的关键内容是：

```text
initializing Ingest server
sailor-ingest.sock → sailor-ingest.sock.stale
The file cannot be accessed by the system.
```

这把排查范围从业务 SQL 缩小到 Docker 的启动阶段。数据库还没启动，修改应用查询语句不会解决问题。

## 先确认报错对象是什么

后端日志与窗口信息一致：Docker 无法重命名运行目录中的套接字文件。目录检查显示相关对象带有 ReparsePoint 属性；该目录中是运行时通信文件，不是 PostgreSQL 的业务数据。

Docker 的问题库中也有 [相同 sailor-ingest 报错的记录](https://github.com/docker/desktop-feedback/issues/676)。它提供了排查线索，但本机恢复是否成功，仍然要靠启动后的检查确认。

错误窗口同时提供“恢复出厂设置”。这次没有采用，因为需要保留已迁移的数据卷，不应把重置当作第一步。

## 处理一个文件后，出现第二处同类错误

先退出失败的 Docker 进程，核对运行目录路径和内容，再把目录改名备份，让 Docker 重新生成通信文件。

第一次重启越过了 Ingest 初始化，却在 Secrets Engine 的 `engine.sock` 上出现同类错误。再次检查发现对应目录仅包含这个套接字，于是同样隔离保留。没有读取或删除真实密钥内容，也没有移动数据库卷。

这里值得记录的是处理边界：因为明确知道目录里是什么，才做目录改名。若目录里还含有其他业务数据，就不能照搬这个步骤。本文也不提供一条不加检查就递归删除目录的命令。

## 恢复要有结果支撑

重新启动后，Docker Compose 报告原 PostgreSQL 容器 Healthy。随后核对数据数量仍为 11 个项目、12 个版本、28 条调用和 60 个检查点。

再执行完整测试，得到 48 项通过；Alembic 结构检查通过。工作台恢复启动，健康接口标记数据库为 PostgreSQL，首页返回正常。

这些结果分别验证了容器运行、数据保留、业务流程与页面可访问。仅仅看到 Docker 窗口不再报错，还不足以说明应用已经恢复。

## 技术完成和交付完成分开记录

验收后，迁移文件已暂存，但 Git 提交连续遇到自动权限审核超时，因此当时尚未推送。这个阻塞属于开发环境的执行权限，不是数据库或测试失败。

写博客时也要保留这个区别：本地已经实现什么，真实验证了什么，仓库或网站实际交付到哪里，都应分别陈述。

## 留给下一次的顺序

这次排障顺序是：确认服务状态，读启动日志，定位具体文件，检查数据边界，做可恢复的最小处理，再验证数据和应用。它比看到连接失败就反复重跑全部测试更有效。

此前的 SQLite 备份继续保留，隔离的运行目录也没有被删除。未来如果再出现类似问题，仍需从当次日志判断，不把这次的原因预设为唯一答案。

上一篇：[PostgreSQL 迁移](/posts/framepilot-05-postgresql-migration/)。[返回 FramePilot 专栏](/archive/?tag=FramePilot)。

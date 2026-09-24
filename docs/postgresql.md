# PostgreSQL 迁移说明

## 选型与边界

业务数据使用 PostgreSQL + SQLAlchemy；Alembic 管理业务表版本。LangGraph 使用官方 PostgresSaver，检查点表由 `setup()` 管理。两套表同库但职责分开。当前没有安装 pgvector，RAG 阶段再引入。

原稿、当前稿、暂停编号和历史问题仍保留在 JSONB 快照中，维持现有 API。项目标识、版本号、额度、时间和账本关联独立建列，并有主键、外键、检查约束和查询索引。此迁移没有把人物/场景拆成实体库。

## 关键入口

- `app/database.py`：读取 DATABASE_URL，校验 PostgreSQL 协议，转换 psycopg 连接参数。
- `app/models.py`：SQLAlchemy 表定义，便于理解数据结构。
- `app/storage.py`：短事务与连接池；配额预占用 `SELECT ... FOR UPDATE` 串行化同一项目的检查和写入。
- `migrations/versions/0001_postgres.py`：初始业务表迁移。
- `scripts/init_db.py`：执行 Alembic upgrade head 和 PostgresSaver.setup；应用本身不隐式建表。
- `scripts/migrate_sqlite.py`：停服导入旧库，原文件保留。

## 导入与回退

1. 停止所有旧/新应用写入，确认没有 running 项目。不要仅复制 `.sqlite3` 主文件而漏掉 WAL。
2. 准备空 PostgreSQL 库，配置 DATABASE_URL，运行 `python -m scripts.init_db`。
3. 安装 requirements-migration.txt，执行 `python -m scripts.migrate_sqlite --source data --confirm-stopped`。
4. 工具在源目录 `backups/<时间_编号>/` 生成两个完整 SQLite 备份。
5. 业务记录、历史版本、调用记录、全部图检查点与待处理写入在同一 PostgreSQL 事务内导入。
6. 保留项目/检查点/暂停编号与调用累计数；核对检查点内容后提交。目标非空时拒绝重复导入。
7. 启动新版，核对旧项目的当前状态、版本和暂停信息；不要为验证而擅自确认或修订用户故事。

导入前失败可以继续使用旧程序和原 SQLite 库。新 PostgreSQL 已产生写入后，不能直接切回旧库而不丢失后续变化；当前没有反向迁移工具。不要把 Alembic downgrade 当成数据回退，它会删除业务表。

## 部署范围

Docker Compose 是本机学习配置，数据库只监听回环地址。部署到其他环境需单独设计账号权限、TLS、备份和认证。连接密码放在未提交的 .env，连接池不等于多用户功能。现有 operation_lock 是进程内锁，仍保持单进程运行。

## 验收

真实 PostgreSQL 用例覆盖并发调用预算、重启恢复、协作选择/修改/澄清、自由循环、流式接口、导出/差异及旧 SQLite 暂停迁移。模型全部使用替身，未向 DeepSeek 发送旧故事。每个测试创建独立随机数据库；没有测试配置时跳过集成用例，不能将跳过解释为通过。

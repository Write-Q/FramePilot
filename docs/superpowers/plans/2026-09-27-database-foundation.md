# Database Foundation Implementation Plan

Goal: 将已批准的领域设计落为增量数据库基础，验证项目隔离、历史版本和后续制作关联，不把建表等同于功能上线。
Architecture: 保留 fp_projects/fp_versions/fp_calls 和检查点；以独立归一化领域表承载章节资产与制作。旧流程迁移映射保持旧 ID，不改 LangGraph 状态。
Tech Stack: PostgreSQL 17, SQLAlchemy Core/ORM, Alembic, pytest.

- [x] 先写关系与约束测试，在原结构验证失败。
- [x] app/domain_schema.py / migrations/versions/0002_domain_foundation.py：冻结增量迁移和元数据，项目元信息、章节/剧本、资产、审核任务、制作媒体关系。
- [x] 设计兼容映射与数据迁移，明确当前旧工作流仍为权威，禁止新旧双向写入。
- [x] 临时数据库验证迁移、跨项目拒绝、版本不可改、章节范围、媒体来源、Alembic 漂移与现有回归。
- [x] 本地数据库备份并恢复演练后升级，比较原稿/版本/调用/检查点内容散列。
- [x] 完整字段字典及关系图从实际结构核对，记录尚未接通的服务、界面及生成平台。

当前已有未提交展示修复和博客文件，不覆盖、不批量提交。

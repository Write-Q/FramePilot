---
title: "FramePilot 开发手记 05：从 SQLite 迁移到 PostgreSQL"
description: "保留业务状态、调用预算和 LangGraph 暂停位置的一次数据库迁移。"
date: 2026-09-23
tags: [FramePilot, PostgreSQL, LangGraph, 后端]
slug: framepilot-05-postgresql-migration
draft: true
---

项目最初用 SQLite 验证单机编剧流程。随着开始系统复盘后端架构，这次把业务库迁到 PostgreSQL，用 SQLAlchemy 表达表结构，用 Alembic 管理结构演进，图状态改用 PostgresSaver。

迁移的不只是剧本文本。用户停在哪里、某一版是否审核、模型已经调用多少次，都会影响继续操作是否正确。为此同时迁移业务快照、历史版本、调用账本和图检查点，保留原编号。导入前停服并生成一致性备份，目标库必须为空，导入失败事务回滚。

配额预占从 SQLite 写事务改为锁定 PostgreSQL 项目行。调用模型之前先提交账本，失败也计数；数据库事务不跨越模型网络请求。测试让多个独立连接同时申请额度，验证不会超额。

本轮使用真实 PostgreSQL 与模拟模型验证工作流，没有调用 DeepSeek 验证创作质量。换数据库没有自动带来多用户支持，应用仍保持单进程。pgvector、RAG 和后台队列留给后续业务阶段。

# 分镜工作台 Implementation Plan

> 采用本会话顺序执行；用户已批准先实现分镜闭环，保留并复用当前工作区未提交底座。

**Goal:** 交付可配置模型、生成、编辑、版本化和确认的文字分镜工作台。

**Architecture:** 通用模型配置 → 单次文本适配器 → 版本化 Skill → 原子分镜落库；独立运行表保证幂等和追溯。浏览器只调用业务 API。

**Tech Stack:** FastAPI / Pydantic / SQLAlchemy / PostgreSQL / httpx / 原生 JS / Playwright。

### 1. 专业输出与 Skill

- [x] 在 tests/test_storyboard_planning.py 添加来源、计划参数和规则测试，先运行观察缺失失败。
- [x] 扩展 app/production/contracts.py，新增 planning.py 和 skills/*.md：版本清单、来源 ID、输入包、输出 schema、规则提示。
- [x] 运行 `.venv/Scripts/python.exe -m pytest tests/test_storyboard_planning.py -q` 至通过。

### 2. 运行记录、模型执行与 HTTP

- [x] tests/test_storyboard_generation.py 验证固定配置、幂等、不自动重试、不采用过期结果、跨项目拒绝；适配器用 httpx.MockTransport。
- [x] schema.py + 冻结迁移 0006 新增 runs；store.py 抽出同事务创建方法；generation.py 管理预约/完成/失败；chat.py 负责单次协议。
- [x] api.py 新增生成、运行列表、标记中断；main.py 增加测试注入和页面路由。
- [x] 临时库运行测试；使用现有 scripts.test_local，绝不针对业务库清表或自动迁移。

### 3. 分镜工作台

- [x] 在 tests/storyboard-ux.test.cjs + test_storyboard_browser.py 添加完整浏览器交互回归并先确认页面缺失失败。
- [x] 新增 storyboard.html/css/js，编剧页提供带项目编号跳转；模型配置通过明确表单保存，只填写密钥环境变量名。
- [x] 浏览器验证生成、编辑、保存新版本、确认、历史只读、增删排序、移动端和错误场景。

### 4. 收尾

- [x] 跑相关测试及既有回归，检查 git diff，审查敏感输入、并发、来源、状态与 UI 未保存保护。
- [x] 更新工作台说明与本轮足迹，明确真实模型未实测、迁移未应用业务库、提交状态。

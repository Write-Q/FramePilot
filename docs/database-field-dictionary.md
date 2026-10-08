# 数据库字段字典：领域基础 v1

本字典根据 app/domain_schema.py 的实际元数据生成。新增32张领域表，旧三张业务表保留。建表不等于界面或生成能力已经实现。

## 阅读约定

内部英文用于接口和关联，中文用于呈现。所有版本记录为追加保存；不可变规则由 Alembic 触发器实现，不能仅运行 metadata.create_all。空值与默认值如下。

## 项目显示信息 — `fp_project_details`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `name` | 显示名称 | `TEXT` | 否 | `无` |

| `synopsis` | 项目简介 | `TEXT` | 否 | `` |

| `row_version` | 并发修改版本标记 | `INTEGER` | 否 | `1` |

| `updated_at` | 更新时间 | `DATETIME` | 否 | `now()` |

| `last_opened_at` | 最近打开时间 | `DATETIME` | 是 | `无` |

| `archived_at` | 归档时间，空表示未归档 | `DATETIME` | 是 | `无` |


主键：project_id

- 检查：`row_version > 0`

- 外键：project_id → fp_projects.id

- 索引：`ix_fp_project_details_updated` (updated_at)

## 章节 — `fp_chapters`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `title` | 标题 | `TEXT` | 否 | `无` |

| `position` | 所属集合内顺序，从1开始 | `INTEGER` | 否 | `无` |

| `row_version` | 并发修改版本标记 | `INTEGER` | 否 | `1` |

| `archived_at` | 归档时间，空表示未归档 | `DATETIME` | 是 | `无` |


主键：id

- 检查：`position > 0`

- 检查：`row_version > 0`

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 索引：`ix_fp_chapters_project` (project_id)

- 索引：`uq_fp_chapters_active_position` (project_id, position)

## 作品要求版本 — `fp_project_brief_versions`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `version_no` | 所属对象内版本号 | `INTEGER` | 否 | `无` |

| `schema_version` | 内容数据约定版本 | `INTEGER` | 否 | `1` |

| `content` | 结构化内容 | `JSONB` | 否 | `'{}'::jsonb` |


主键：id

- 检查：`version_no > 0`

- 检查：`schema_version > 0`

- 唯一：project_id, id

- 唯一：project_id, version_no

- 外键：project_id → fp_projects.id

- 索引：`ix_fp_project_brief_versions_project` (project_id)

## 章节原始输入版本 — `fp_chapter_input_versions`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `chapter_id` | 所属章节 | `VARCHAR(64)` | 否 | `无` |

| `version_no` | 所属对象内版本号 | `INTEGER` | 否 | `无` |

| `schema_version` | 内容数据约定版本 | `INTEGER` | 否 | `1` |

| `original_story` | 用户输入原文 | `TEXT` | 否 | `无` |

| `constraints` | 用户创作要求 | `TEXT` | 否 | `` |


主键：id

- 检查：`version_no > 0`

- 检查：`schema_version > 0`

- 唯一：chapter_id, version_no

- 唯一：project_id, chapter_id, id

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, chapter_id → fp_chapters.project_id, fp_chapters.id

- 索引：`ix_fp_chapter_input_versions_project` (project_id)

## 剧本身份 — `fp_scripts`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `chapter_id` | 所属章节 | `VARCHAR(64)` | 否 | `无` |

| `current_version_id` | 当前剧本版本指针 | `VARCHAR(64)` | 是 | `无` |

| `row_version` | 并发修改版本标记 | `INTEGER` | 否 | `1` |


主键：id

- 检查：`row_version > 0`

- 唯一：chapter_id

- 唯一：project_id, chapter_id, id

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, chapter_id → fp_chapters.project_id, fp_chapters.id

- 外键：project_id, id, current_version_id → fp_script_versions.project_id, fp_script_versions.script_id, fp_script_versions.id

- 索引：`ix_fp_scripts_project` (project_id)

## 剧本正文版本 — `fp_script_versions`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `script_id` | 所属剧本 | `VARCHAR(64)` | 否 | `无` |

| `version_no` | 所属对象内版本号 | `INTEGER` | 否 | `无` |

| `schema_version` | 内容数据约定版本 | `INTEGER` | 否 | `1` |

| `chapter_id` | 所属章节 | `VARCHAR(64)` | 否 | `无` |

| `parent_version_id` | 上一正文版本 | `VARCHAR(64)` | 是 | `无` |

| `input_version_id` | 采用的用户输入版本 | `VARCHAR(64)` | 是 | `无` |

| `brief_version_id` | 采用的作品要求版本 | `VARCHAR(64)` | 是 | `无` |

| `body` | 剧本正文 | `TEXT` | 否 | `无` |

| `card` | 当版十维概括 | `JSONB` | 否 | `'{}'::jsonb` |


主键：id

- 检查：`(version_no = 1 AND parent_version_id IS NULL) OR (version_no > 1 AND parent_version_id IS NOT NULL)`

- 检查：`version_no > 0`

- 检查：`schema_version > 0`

- 唯一：project_id, chapter_id, id

- 唯一：project_id, id

- 唯一：project_id, script_id, id

- 唯一：script_id, version_no

- 外键：project_id → fp_projects.id

- 外键：project_id, brief_version_id → fp_project_brief_versions.project_id, fp_project_brief_versions.id

- 外键：project_id, chapter_id, input_version_id → fp_chapter_input_versions.project_id, fp_chapter_input_versions.chapter_id, fp_chapter_input_versions.id

- 外键：project_id, chapter_id, script_id → fp_scripts.project_id, fp_scripts.chapter_id, fp_scripts.id

- 外键：project_id, script_id → fp_scripts.project_id, fp_scripts.id

- 外键：project_id, script_id, parent_version_id → fp_script_versions.project_id, fp_script_versions.script_id, fp_script_versions.id

- 索引：`ix_fp_script_versions_project` (project_id)

## 资产身份 — `fp_assets`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `asset_type` | 资产类型：人物/地点/道具 | `VARCHAR(64)` | 否 | `无` |

| `scope_chapter_id` | 限定章节；空表示项目内共有 | `VARCHAR(64)` | 是 | `无` |

| `display_name` | 用户可见名称 | `TEXT` | 否 | `无` |

| `row_version` | 并发修改版本标记 | `INTEGER` | 否 | `1` |

| `archived_at` | 归档时间，空表示未归档 | `DATETIME` | 是 | `无` |


主键：id

- 检查：`asset_type IN ('character', 'location', 'prop')`

- 检查：`row_version > 0`

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, scope_chapter_id → fp_chapters.project_id, fp_chapters.id

- 索引：`ix_fp_assets_project` (project_id)

- 索引：`ix_fp_assets_scope` (project_id, asset_type, scope_chapter_id)

## 资产设定版本 — `fp_asset_versions`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `asset_id` | 资产身份 | `VARCHAR(64)` | 否 | `无` |

| `version_no` | 所属对象内版本号 | `INTEGER` | 否 | `无` |

| `schema_version` | 内容数据约定版本 | `INTEGER` | 否 | `1` |

| `definition` | 资产设定快照 | `JSONB` | 否 | `'{}'::jsonb` |


主键：id

- 检查：`version_no > 0`

- 检查：`schema_version > 0`

- 唯一：asset_id, version_no

- 唯一：project_id, asset_id, id

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, asset_id → fp_assets.project_id, fp_assets.id

- 索引：`ix_fp_asset_versions_project` (project_id)

## 资产版本审批 — `fp_asset_version_decisions`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `decision_seq` | 数据库分配的审批顺序，允许有间隔 | `BIGINT` | 否 | `数据库序列` |

| `asset_version_id` | 确切资产版本 | `VARCHAR(64)` | 否 | `无` |

| `decision` | 批准/拒绝/撤销 | `VARCHAR(64)` | 否 | `无` |

| `reason` | 决定理由 | `TEXT` | 否 | `` |


主键：id

- 检查：`decision IN ('approved', 'rejected', 'revoked')`

- 唯一：decision_seq

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, asset_version_id → fp_asset_versions.project_id, fp_asset_versions.id

- 索引：`ix_fp_asset_version_decisions_project` (project_id)

## 章节资产选择 — `fp_chapter_asset_links`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `chapter_id` | 所属章节 | `VARCHAR(64)` | 否 | `无` |

| `asset_id` | 资产身份 | `VARCHAR(64)` | 否 | `无` |

| `selected_version_id` | 章节当前选择的资产版本 | `VARCHAR(64)` | 是 | `无` |


主键：id

- 唯一：chapter_id, asset_id

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, asset_id → fp_assets.project_id, fp_assets.id

- 外键：project_id, asset_id, selected_version_id → fp_asset_versions.project_id, fp_asset_versions.asset_id, fp_asset_versions.id

- 外键：project_id, chapter_id → fp_chapters.project_id, fp_chapters.id

- 索引：`ix_fp_chapter_asset_links_project` (project_id)

## 剧本资产版本引用 — `fp_script_asset_refs`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `chapter_id` | 所属章节 | `VARCHAR(64)` | 否 | `无` |

| `script_version_id` | 确切剧本版本 | `VARCHAR(64)` | 否 | `无` |

| `asset_id` | 资产身份 | `VARCHAR(64)` | 否 | `无` |

| `asset_version_id` | 确切资产版本 | `VARCHAR(64)` | 否 | `无` |


主键：id

- 唯一：project_id, id

- 唯一：script_version_id, asset_id

- 外键：project_id → fp_projects.id

- 外键：project_id, asset_id, asset_version_id → fp_asset_versions.project_id, fp_asset_versions.asset_id, fp_asset_versions.id

- 外键：project_id, chapter_id, script_version_id → fp_script_versions.project_id, fp_script_versions.chapter_id, fp_script_versions.id

- 索引：`ix_fp_script_asset_refs_project` (project_id)

## 资产来源 — `fp_asset_origins`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `asset_version_id` | 确切资产版本 | `VARCHAR(64)` | 否 | `无` |

| `source_script_version_id` | 资产来源剧本版本 | `VARCHAR(64)` | 否 | `无` |

| `source_quote` | 原文依据 | `TEXT` | 否 | `` |


主键：id

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, asset_version_id → fp_asset_versions.project_id, fp_asset_versions.id

- 外键：project_id, source_script_version_id → fp_script_versions.project_id, fp_script_versions.id

- 索引：`ix_fp_asset_origins_project` (project_id)

## 审核轮次 — `fp_review_runs`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `script_version_id` | 确切剧本版本 | `VARCHAR(64)` | 否 | `无` |

| `task_id` | 生成任务 | `VARCHAR(64)` | 是 | `无` |

| `rubric_version` | 审核规则版本 | `VARCHAR(64)` | 否 | `无` |

| `result` | 审核结果 | `JSONB` | 否 | `'{}'::jsonb` |


主键：id

- 唯一：project_id, id

- 唯一：project_id, script_version_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, script_version_id → fp_script_versions.project_id, fp_script_versions.id

- 外键：project_id, task_id → fp_generation_tasks.project_id, fp_generation_tasks.id

- 索引：`ix_fp_review_runs_project` (project_id)

## 审核问题 — `fp_review_issues`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `review_run_id` | 所属审核轮次 | `VARCHAR(64)` | 否 | `无` |

| `category` | 问题分类 | `VARCHAR(64)` | 否 | `无` |

| `description` | 问题说明 | `TEXT` | 否 | `无` |

| `suggestion` | 修改建议 | `TEXT` | 否 | `` |

| `evidence` | 结构化引用依据 | `JSONB` | 否 | `'{}'::jsonb` |

| `needs_user` | 是否需要用户补充 | `BOOLEAN` | 否 | `false` |

| `fingerprint` | 问题比较标记，非跨轮主键 | `VARCHAR(64)` | 是 | `无` |


主键：id

- 唯一：project_id, id

- 唯一：project_id, review_run_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, review_run_id → fp_review_runs.project_id, fp_review_runs.id

- 索引：`ix_fp_review_issues_project` (project_id)

## 问题关联资产 — `fp_review_issue_assets`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `review_issue_id` | 审核问题 | `VARCHAR(64)` | 否 | `无` |

| `asset_version_id` | 确切资产版本 | `VARCHAR(64)` | 否 | `无` |


主键：id

- 唯一：project_id, id

- 唯一：review_issue_id, asset_version_id

- 外键：project_id → fp_projects.id

- 外键：project_id, asset_version_id → fp_asset_versions.project_id, fp_asset_versions.id

- 外键：project_id, review_issue_id → fp_review_issues.project_id, fp_review_issues.id

- 索引：`ix_fp_review_issue_assets_project` (project_id)

## 用户提交 — `fp_revision_requests`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `script_id` | 所属剧本 | `VARCHAR(64)` | 否 | `无` |

| `base_version_id` | 本次操作基于的正文版本 | `VARCHAR(64)` | 否 | `无` |

| `review_run_id` | 所属审核轮次 | `VARCHAR(64)` | 是 | `无` |

| `action` | 用户操作类型 | `VARCHAR(64)` | 否 | `无` |

| `feedback` | 用户补充原文 | `TEXT` | 否 | `` |

| `idempotency_key` | 防重复提交标识 | `VARCHAR(64)` | 否 | `无` |


主键：id

- 检查：`action IN ('revise', 'clarify', 'confirm')`

- 唯一：project_id, id

- 唯一：project_id, idempotency_key

- 唯一：project_id, review_run_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, base_version_id, review_run_id → fp_review_runs.project_id, fp_review_runs.script_version_id, fp_review_runs.id

- 外键：project_id, script_id, base_version_id → fp_script_versions.project_id, fp_script_versions.script_id, fp_script_versions.id

- 索引：`ix_fp_revision_requests_project` (project_id)

## 逐条处理决策 — `fp_issue_decisions`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `request_id` | 用户提交记录 | `VARCHAR(64)` | 否 | `无` |

| `review_run_id` | 所属审核轮次 | `VARCHAR(64)` | 否 | `无` |

| `issue_id` | 问题记录 | `VARCHAR(64)` | 否 | `无` |

| `choice` | 处理方式 | `VARCHAR(64)` | 否 | `无` |

| `instruction` | 采用/替换/保留的具体内容 | `TEXT` | 否 | `` |


主键：id

- 检查：`choice IN ('adopt', 'replace', 'preserve', 'accept')`

- 唯一：project_id, id

- 唯一：request_id, issue_id

- 外键：project_id → fp_projects.id

- 外键：project_id, review_run_id, issue_id → fp_review_issues.project_id, fp_review_issues.review_run_id, fp_review_issues.id

- 外键：project_id, review_run_id, request_id → fp_revision_requests.project_id, fp_revision_requests.review_run_id, fp_revision_requests.id

- 索引：`ix_fp_issue_decisions_project` (project_id)

## 生成任务 — `fp_generation_tasks`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `chapter_id` | 所属章节 | `VARCHAR(64)` | 否 | `无` |

| `request_id` | 用户提交记录 | `VARCHAR(64)` | 是 | `无` |

| `input_version_id` | 采用的用户输入版本 | `VARCHAR(64)` | 是 | `无` |

| `brief_version_id` | 采用的作品要求版本 | `VARCHAR(64)` | 是 | `无` |

| `source_version_id` | 任务输入正文版本 | `VARCHAR(64)` | 是 | `无` |

| `result_version_id` | 任务输出正文版本 | `VARCHAR(64)` | 是 | `无` |

| `input_manifest` | 任务输入说明快照，关系必须另用外键表达 | `JSONB` | 否 | `'{}'::jsonb` |

| `workflow_version` | 工作流定义版本 | `VARCHAR(64)` | 否 | `无` |

| `status` | 执行状态 | `VARCHAR(64)` | 否 | `pending` |

| `row_version` | 并发修改版本标记 | `INTEGER` | 否 | `1` |

| `finished_at` | 结束时间 | `DATETIME` | 是 | `无` |


主键：id

- 检查：`status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')`

- 检查：`row_version > 0`

- 唯一：project_id, chapter_id, id

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, brief_version_id → fp_project_brief_versions.project_id, fp_project_brief_versions.id

- 外键：project_id, chapter_id → fp_chapters.project_id, fp_chapters.id

- 外键：project_id, chapter_id, input_version_id → fp_chapter_input_versions.project_id, fp_chapter_input_versions.chapter_id, fp_chapter_input_versions.id

- 外键：project_id, chapter_id, result_version_id → fp_script_versions.project_id, fp_script_versions.chapter_id, fp_script_versions.id

- 外键：project_id, chapter_id, source_version_id → fp_script_versions.project_id, fp_script_versions.chapter_id, fp_script_versions.id

- 外键：project_id, request_id → fp_revision_requests.project_id, fp_revision_requests.id

- 索引：`ix_fp_generation_tasks_project` (project_id)

- 索引：`ix_fp_tasks_status` (project_id, status)

## 任务执行尝试 — `fp_task_attempts`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `task_id` | 生成任务 | `VARCHAR(64)` | 否 | `无` |

| `attempt_no` | 同任务尝试次数 | `INTEGER` | 否 | `无` |

| `status` | 执行状态 | `VARCHAR(64)` | 否 | `running` |

| `started_at` | 开始时间 | `DATETIME` | 否 | `now()` |

| `finished_at` | 结束时间 | `DATETIME` | 是 | `无` |

| `error_code` | 错误类别 | `VARCHAR(64)` | 是 | `无` |


主键：id

- 检查：`attempt_no > 0`

- 唯一：project_id, id

- 唯一：task_id, attempt_no

- 外键：project_id → fp_projects.id

- 外键：project_id, task_id → fp_generation_tasks.project_id, fp_generation_tasks.id

- 索引：`ix_fp_task_attempts_project` (project_id)

## 模型调用来源 — `fp_call_links`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `call_id` | 原调用账本记录 | `INTEGER` | 否 | `无` |

| `task_attempt_id` | 确切任务尝试 | `VARCHAR(64)` | 否 | `无` |

| `provider` | 模型服务提供方 | `VARCHAR(64)` | 是 | `无` |

| `model` | 模型名称 | `VARCHAR(64)` | 是 | `无` |

| `parameters` | 调用参数快照，不保存密钥 | `JSONB` | 否 | `'{}'::jsonb` |


主键：id

- 唯一：call_id

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, call_id → fp_calls.project_id, fp_calls.id

- 外键：project_id, task_attempt_id → fp_task_attempts.project_id, fp_task_attempts.id

- 索引：`ix_fp_call_links_project` (project_id)

## 工作流会话 — `fp_workflow_sessions`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `chapter_id` | 所属章节 | `VARCHAR(64)` | 否 | `无` |

| `task_id` | 生成任务 | `VARCHAR(64)` | 否 | `无` |

| `thread_id` | LangGraph执行线程标识 | `VARCHAR(64)` | 否 | `无` |

| `workflow_version` | 工作流定义版本 | `VARCHAR(64)` | 否 | `无` |


主键：id

- 唯一：project_id, id

- 唯一：thread_id

- 外键：project_id → fp_projects.id

- 外键：project_id, chapter_id, task_id → fp_generation_tasks.project_id, fp_generation_tasks.chapter_id, fp_generation_tasks.id

- 索引：`ix_fp_workflow_sessions_project` (project_id)

## 场戏拆解版本 — `fp_breakdown_versions`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `script_version_id` | 确切剧本版本 | `VARCHAR(64)` | 否 | `无` |

| `version_no` | 所属对象内版本号 | `INTEGER` | 否 | `无` |

| `schema_version` | 内容数据约定版本 | `INTEGER` | 否 | `1` |

| `content` | 结构化内容 | `JSONB` | 否 | `'{}'::jsonb` |


主键：id

- 检查：`version_no > 0`

- 检查：`schema_version > 0`

- 唯一：project_id, id

- 唯一：project_id, script_version_id, id

- 唯一：script_version_id, version_no

- 外键：project_id → fp_projects.id

- 外键：project_id, script_version_id → fp_script_versions.project_id, fp_script_versions.id

- 索引：`ix_fp_breakdown_versions_project` (project_id)

## 场戏 — `fp_scenes`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `breakdown_version_id` | 确切场戏拆解版本 | `VARCHAR(64)` | 否 | `无` |

| `position` | 所属集合内顺序，从1开始 | `INTEGER` | 否 | `无` |

| `title` | 标题 | `TEXT` | 否 | `无` |

| `content` | 结构化内容 | `JSONB` | 否 | `'{}'::jsonb` |

| `continuity` | 该场戏或镜头中的临时剧情状态 | `JSONB` | 否 | `'{}'::jsonb` |


主键：id

- 检查：`position > 0`

- 唯一：breakdown_version_id, position

- 唯一：project_id, breakdown_version_id, id

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, breakdown_version_id → fp_breakdown_versions.project_id, fp_breakdown_versions.id

- 索引：`ix_fp_scenes_project` (project_id)

## 分镜版本 — `fp_storyboard_versions`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `breakdown_version_id` | 确切场戏拆解版本 | `VARCHAR(64)` | 否 | `无` |

| `version_no` | 所属对象内版本号 | `INTEGER` | 否 | `无` |

| `schema_version` | 内容数据约定版本 | `INTEGER` | 否 | `1` |

| `content` | 结构化内容 | `JSONB` | 否 | `'{}'::jsonb` |


主键：id

- 检查：`version_no > 0`

- 检查：`schema_version > 0`

- 唯一：breakdown_version_id, version_no

- 唯一：project_id, breakdown_version_id, id

- 唯一：project_id, breakdown_version_id, id

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, breakdown_version_id → fp_breakdown_versions.project_id, fp_breakdown_versions.id

- 索引：`ix_fp_storyboard_versions_project` (project_id)

## 镜头 — `fp_shots`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `storyboard_version_id` | 确切分镜版本 | `VARCHAR(64)` | 否 | `无` |

| `breakdown_version_id` | 确切场戏拆解版本 | `VARCHAR(64)` | 否 | `无` |

| `scene_id` | 所属场戏 | `VARCHAR(64)` | 否 | `无` |

| `position` | 所属集合内顺序，从1开始 | `INTEGER` | 否 | `无` |

| `content` | 结构化内容 | `JSONB` | 否 | `'{}'::jsonb` |

| `continuity` | 该场戏或镜头中的临时剧情状态 | `JSONB` | 否 | `'{}'::jsonb` |


主键：id

- 检查：`position > 0`

- 唯一：project_id, id

- 唯一：storyboard_version_id, position

- 外键：project_id → fp_projects.id

- 外键：project_id, breakdown_version_id, scene_id → fp_scenes.project_id, fp_scenes.breakdown_version_id, fp_scenes.id

- 外键：project_id, breakdown_version_id, storyboard_version_id → fp_storyboard_versions.project_id, fp_storyboard_versions.breakdown_version_id, fp_storyboard_versions.id

- 索引：`ix_fp_shots_project` (project_id)

## 媒体文件 — `fp_media_files`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `storage_key` | 稳定存储位置，不存临时签名URL | `TEXT` | 否 | `无` |

| `media_type` | 媒体类型 | `VARCHAR(64)` | 否 | `无` |

| `checksum` | 文件内容校验值 | `VARCHAR(64)` | 是 | `无` |

| `size_bytes` | 文件大小字节数 | `BIGINT` | 否 | `无` |

| `metadata` | 媒体尺寸/时长等属性 | `JSONB` | 否 | `'{}'::jsonb` |


主键：id

- 检查：`size_bytes >= 0`

- 唯一：project_id, id

- 唯一：storage_key

- 外键：project_id → fp_projects.id

- 索引：`ix_fp_media_files_project` (project_id)

## 资产媒体引用 — `fp_asset_media_links`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `asset_version_id` | 确切资产版本 | `VARCHAR(64)` | 否 | `无` |

| `media_file_id` | 媒体文件 | `VARCHAR(64)` | 否 | `无` |

| `role` | 引用用途，如参考/输入/输出 | `VARCHAR(64)` | 否 | `reference` |


主键：id

- 唯一：asset_version_id, media_file_id, role

- 唯一：project_id, id

- 外键：project_id → fp_projects.id

- 外键：project_id, asset_version_id → fp_asset_versions.project_id, fp_asset_versions.id

- 外键：project_id, media_file_id → fp_media_files.project_id, fp_media_files.id

- 索引：`ix_fp_asset_media_links_project` (project_id)

## 镜头媒体引用 — `fp_shot_media_links`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `shot_id` | 确切镜头记录 | `VARCHAR(64)` | 否 | `无` |

| `media_file_id` | 媒体文件 | `VARCHAR(64)` | 否 | `无` |

| `role` | 引用用途，如参考/输入/输出 | `VARCHAR(64)` | 否 | `output` |


主键：id

- 唯一：project_id, id

- 唯一：shot_id, media_file_id, role

- 外键：project_id → fp_projects.id

- 外键：project_id, media_file_id → fp_media_files.project_id, fp_media_files.id

- 外键：project_id, shot_id → fp_shots.project_id, fp_shots.id

- 索引：`ix_fp_shot_media_links_project` (project_id)

## 场戏资产引用 — `fp_scene_asset_refs`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `scene_id` | 所属场戏 | `VARCHAR(64)` | 否 | `无` |

| `asset_id` | 资产身份 | `VARCHAR(64)` | 否 | `无` |

| `asset_version_id` | 确切资产版本 | `VARCHAR(64)` | 否 | `无` |


主键：id

- 唯一：project_id, id

- 唯一：scene_id, asset_id

- 外键：project_id → fp_projects.id

- 外键：project_id, asset_id, asset_version_id → fp_asset_versions.project_id, fp_asset_versions.asset_id, fp_asset_versions.id

- 外键：project_id, scene_id → fp_scenes.project_id, fp_scenes.id

- 索引：`ix_fp_scene_asset_refs_project` (project_id)

## 镜头资产引用 — `fp_shot_asset_refs`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `shot_id` | 确切镜头记录 | `VARCHAR(64)` | 否 | `无` |

| `asset_id` | 资产身份 | `VARCHAR(64)` | 否 | `无` |

| `asset_version_id` | 确切资产版本 | `VARCHAR(64)` | 否 | `无` |


主键：id

- 唯一：project_id, id

- 唯一：shot_id, asset_id

- 外键：project_id → fp_projects.id

- 外键：project_id, asset_id, asset_version_id → fp_asset_versions.project_id, fp_asset_versions.asset_id, fp_asset_versions.id

- 外键：project_id, shot_id → fp_shots.project_id, fp_shots.id

- 索引：`ix_fp_shot_asset_refs_project` (project_id)

## 任务媒体引用 — `fp_task_media_links`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `task_id` | 生成任务 | `VARCHAR(64)` | 否 | `无` |

| `media_file_id` | 媒体文件 | `VARCHAR(64)` | 否 | `无` |

| `role` | 引用用途，如参考/输入/输出 | `VARCHAR(64)` | 否 | `无` |


主键：id

- 检查：`role IN ('input', 'output')`

- 唯一：project_id, id

- 唯一：task_id, media_file_id, role

- 外键：project_id → fp_projects.id

- 外键：project_id, media_file_id → fp_media_files.project_id, fp_media_files.id

- 外键：project_id, task_id → fp_generation_tasks.project_id, fp_generation_tasks.id

- 索引：`ix_fp_task_media_links_project` (project_id)

## 任务目标镜头 — `fp_task_shot_links`

| 字段 | 含义 | 类型 | 可空 | 默认值 |

|---|---|---|---|---|

| `id` | 内部唯一标识 | `VARCHAR(64)` | 否 | `无` |

| `project_id` | 所属项目 | `VARCHAR(64)` | 否 | `无` |

| `created_at` | 记录创建时间（回填记录为导入时间） | `DATETIME` | 否 | `now()` |

| `task_id` | 生成任务 | `VARCHAR(64)` | 否 | `无` |

| `shot_id` | 确切镜头记录 | `VARCHAR(64)` | 否 | `无` |


主键：id

- 唯一：project_id, id

- 唯一：task_id, shot_id

- 外键：project_id → fp_projects.id

- 外键：project_id, shot_id → fp_shots.project_id, fp_shots.id

- 外键：project_id, task_id → fp_generation_tasks.project_id, fp_generation_tasks.id

- 索引：`ix_fp_task_shot_links_project` (project_id)

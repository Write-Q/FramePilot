# 业务库升级至独立分镜审核版本

- 用户授权：确认业务库需要升级后，用户同意下一步。本轮执行本机业务库备份、隔离恢复演练、暂停写入、迁移及只读验收，不触发付费模型或修改故事。
- 采用verification-before-completion技能：以备份可恢复、迁移版本、既有表指纹和只读API证据验收。
- 保留现有未提交改动，在当前工作区操作，不暂存/提交其他任务。开始额度主要剩余82%、周剩余42%。
- 已读数据库运维约定：迁移前备份并用verify_domain_backup隔离恢复；正式停写；升级后比较原六表指纹。本轮计划扩大到所有既有业务表，排除alembic版本及checkpoint迁移元信息等预期变化。
- 当前：初始检查命令因PowerShell内嵌引号解析失败，未执行任何数据库操作；将改用本地脚本避免shell转义。

## 备份与演练

- 当前版本0004_story_game，业务库41张public表（含alembic/checkpoint元信息），无活动会话及应用Python进程。Docker已健康，无需重启。
- 完整备份 `.runtime/db-upgrade-20261020-01a151/before-0004.dump`，275221字节；SHA256 `0d5d28d1c343a976894618595e438539639196934382ceecf86ebaf45e061415`。已检查备份目录可读。
- 运行既有scripts.verify_domain_backup，在随机临时库恢复成功并升级head；旧六表指纹一致，13项目/14正文版本，临时库按工具finally清理。业务库41表全量行内容SHA256核对在演练前后相同。
- 初始running查询误用了快照顶层status；正式迁移门禁改用snapshot.state.status，并额外检查started调用，不以初始0作为充分证据。
- 下一步正式迁移前再次核对备份哈希、全部表指纹、无活动会话与未完成调用；不改变任何已有项目状态。

## 正式迁移与验收

- 门禁：备份SHA256一致、41表迁移前指纹一致、无活动数据库会话、snapshot.state.status为running项目0个、started调用0个。操作前没有运行应用，故未终止或重启任何应用进程；未改变项目运行状态。
- 已执行initialize：0004_story_game→0005_production_foundation→0006_storyboard_runs→0007_storyboard_reviews。
- 新增5表：fp_model_profiles、fp_model_profile_versions、fp_storyboard_confirmations、fp_storyboard_runs、fp_storyboard_review_runs；审核历史保护触发器存在。
- 迁移前后除alembic_version外40张既有public表（含checkpoint_migrations）逐表行数与SHA256全部一致。Alembic command.check通过：No new upgrade operations detected。
- 只读验收：TestClient加载当前应用，检查health、storyboard页面、review脚本、adapters、model-profiles均200，OpenAPI存在独立review-runs路径。全部13个旧项目/版本、分镜列表与生成运行列表GET均200。通过禁止模型调用的provider验证，模型调用0次，未创建业务测试数据。验收结束全表指纹与迁移后相同。
- 完整运维证据与前后指纹：`.runtime/db-upgrade-20261020-01a151/evidence.json`。备份位于同目录before-0004.dump，含真实业务数据且被.gitignore排除，不发布/提交。
- 回退原则：若未来需恢复，先将该dump恢复到新库并验证后切换；不直接downgrade或覆盖唯一业务库。当前迁移成功，无需回退。
- 验证边界：本轮是实际业务库升级及只读API检查；未启动持久应用服务、未做真实模型质量验证。业务库升级已完成，分镜审核功能代码仍依赖当前未提交工作树。未暂存/提交/合并任何任务文件，未清理分支或旧临时库。
- 下一步：启动实际服务并配置review用途模型，在用户选定剧本上显式发起审核，人工评估误报/漏报；这可能产生模型费用，本轮未调用。

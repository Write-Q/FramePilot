# 后期服务、不可变时间线与导出队列

## 需求和分工

- 用户授权成片闭环、阶段检查通过后归档；本子任务遵循主任务方案 `docs/superpowers/plans/2026-10-23-postproduction-01a151.md`。
- 负责 editing_contracts.py、editing_schema.py、editing_service.py、0011_editing.py 和 tests/test_editing.py。路由、共享 models 注册、渲染器、页面、业务库迁移和提交推送由主任务整合。
- 本记录独立创建，没有覆盖其他任务记录，没有提交任何文件。

## 实现及取舍

- 时间线按分镜系列保存不可变递增版本，项目锁与 expected_version 乐观检查共同防止并发覆盖。
- 仅允许当前剧本、当前确认分镜、当前已选成功视频进入新时间线；裁切不超过解码后的真实时长。旧版本仍可读取，来源或选片变化后禁止新导出。
- 输入 manifest 固定视频、音频的存储标识、SHA256、大小和实际时长。HTTP 不接收路径，WAV 使用 UUID 名和排他创建，限制20MiB、600秒、项目100条；实际 PyAV 解码并核对 WAV 样本数。
- clips/subtitles/audio_tracks 的数量、增益、区间、总时长通过严格契约约束。硬切、原声 gain1、无默认字幕或音轨，不引入外部模型或 TTS。
- 导出任务固定具体时间线版本、内容摘要和 manifest，项目内幂等键，累计100次上限。worker 用 SKIP LOCKED 领取，预检后在事务外渲染，成功输出再交 VideoFiles 真实解码和不可覆盖保存。
- queued/running 可人工 abandon 为 unknown；claim 身份让晚到结果不能覆盖。重启遗留 running 不重新领取，不自动渲染或重试。
- 人工验收另存追加历史；渲染成功不会自动标为已验收。预览和下载前重新校验文件大小和 SHA256。
- 0011 为冻结 schema 迁移，创建不可变历史和导出状态转换触发器，按 project + id 复合外键隔离；有后期历史时拒绝破坏性回退。

## 验证证据

- 先建立测试，首次运行因 editing_contracts 缺失而失败。随后实现，再增加异常路径测试。
- `.venv/Scripts/python.exe` 执行 tests/test_editing.py：18 passed，28.79秒；仅现有 Starlette/AnyIO BlockingPortal 弃用警告。
- PostgreSQL 测试明确将维护连接切到 database_url().set(database='postgres')，每用例由现有 fixture 创建并删除随机 fp_test_ 临时库，测试初始化真实执行全部迁移；没有迁移或清空业务库。沙箱本地 TCP 首次权限失败，授权提升后的同一隔离测试通过。
- 覆盖真实本地 H.264 输入、实际 WAV 解码、不可变时间线、乐观锁、真实裁切时长、项目隔离、幂等冲突、旧来源拒绝导出、排队后二次来源及文件校验、失败脱敏与不重试、重启遗留状态、并发领取和中断晚到结果、手工验收、成片文件篡改。
- 异常终态测试发现 JSONB None 会保存 JSON null，违背 SQL NULL 输出约束；已改显式 sa.null()，完整18例重跑通过。
- compileall 和 git diff --check 通过；仅共享文件已有 LF/CRLF 提示。

## 局限、未完成及交接

- 本单元测试的成功导出通过注入返回真实本地 MP4 字节的渲染函数来验证队列/存储边界，不能作为 FFmpeg 合成、字幕可见性或真实模型质量的效果验证。主任务负责实际渲染器、浏览器和端到端集成验收。
- 本任务仅接受既有成功视频运行记录；供应商无关的“本地视频素材”入库需要独立来源设计，由主任务决定后续范围，不能冒标为 AI 生成。
- 新增文件待主任务整合、核对并提交推送。没有宣称业务迁移、远程同步或后台持续执行完成。
- 下一步：主任务接入 HTTP 与独立 worker，实测真实渲染成片并完成整体迁移/备份/远程 SHA 归档。

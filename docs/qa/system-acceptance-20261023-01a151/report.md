# 模拟供应商系统验收

日期：2026-10-23。验收对象为当前工作区（含尚未提交的审核、媒体和视频功能），不是GitHub既有提交。

## 方法与隔离

文本规划、审核、图片、视频供应商全部为确定性替身；视频内容是本地PyAV实际编码的短H264片段。PostgreSQL、Alembic、图片解码、视频解码、文件读写、HTTP Range和Edge网页为真实执行。

TEST_DATABASE_URL使用本机postgres维护库连接，tests/conftest.py每例创建并只清理随机fp_test_UUID；测试不接收业务库作为数据目标。图片/视频使用临时目录，未发外部收费生成请求，未迁移或清空业务库。

## 验收矩阵

| 范围 | 证据 | 本轮检查 |
| --- | --- | --- |
| 完整制作链路 | test_system_acceptance.py::test_complete_production_restart_and_version_invalidation | 已确认剧本→分镜生成→独立审核→确认→图片生成/选用→视频输入→提交→应用对象重建→查询→真实解码→Range读取→选用 |
| 跨模块版本联动 | 同上及原分镜/审核/媒体测试 | V2不继承V1报告或素材的适用性；旧文件保留可读；无同版本首帧不能准备新视频 |
| 重复提交 | 同上与generation/reviews/media/video_runtime测试 | 原键对账，换参数冲突；重建应用后外部任务ID仍在，只查询原任务 |
| 故障与并发 | test_shot_media.py、test_video_runtime.py | 超时unknown、取消与领取竞争、并发领取、标记未知后晚到结果丢弃、恢复查询后旧claim不能覆盖 |
| 文件与HTTP隔离 | test_video_files.py、test_video_playback.py | 真实解码、损坏/伪视频/越界/超时限制、checksum、HTTP206、跨项目404 |
| 实际网页 | test_storyboard_browser.py、test_media_browser.py、test_video_playback.py | 完整页面脚本、审核与图片交互、视频加载与播放时间推进、人工选用 |
| 故障交互与移动端 | storyboard-media-ux.test.cjs、storyboard-video-ux.test.cjs | 响应丢失保留原键、新版本恢复、门禁、旧响应隔离、390px布局；请求为mock |
| 30镜头规模 | test_system_acceptance.py::test_thirty_shot_plan_roundtrip_and_revision | 30镜头结构、保存、倒序编辑、V1历史和V2确认，不是性能压力测试 |
| 数据约束与迁移 | test_domain_schema.py、test_postgres_schema.py等 | ownership、不可变历史、迁移冻结/一致性、非空历史拒绝危险回退 |

## 不应从本轮推导的结论

- 没有验证真实供应商的认证、模型参数、限流、账单或生成效果；模拟空审核报告不证明分镜没有语义问题。
- 本轮未重复完整备份恢复演练；此前0009备份恢复证据在本机.runtime/db-upgrade-20261023-video-01a151/evidence.json，不能当成本轮新执行结果。
- 不是多用户公网安全评估、长时间浸泡或容量测试；30镜头只做数据流程边界检查。未模拟操作系统断电或直接杀死生产进程。
- 恢复证据包括重建应用/连接实例与人工控制并发，不保证任意供应商均支持同样的查询能力。
- 视频验证是技术解码和文件检查，尚无内容理解、口型/音画同步、跨镜头语义审核或后期成片验收。

## 执行结果

完整回归 **351 passed、0 skipped、0 failed、0 errors**，162.40秒；1条既有Starlette/AnyIO弃用警告，未出现本轮业务断言失败。pytest.xml为该次原始结果，summary.json保存机器可读汇总。30镜头补测1 passed（4.42秒）；两个浏览器mock测试2 passed（1.89秒）。不同批次不合并冒称同次全仓结果。

结论：当前模拟供应商范围内的工程流程验收通过，可以进入下一阶段的视频内容审核开发。新增验收未发现需要修复的业务问题；不据此宣称已可真实生成视频或具备生产部署条件。本轮新增两个跨模块案例，未改变业务实现，未提交或推送。

# 视频持久运行时底座

用户通过主任务要求按顺序继续；供应商仍未选。本子任务只负责独立运行时表、冻结0009迁移、VideoRuntime及测试。主任务负责models/API/UI注册。不自动升级业务库、不提交、不发真实请求。

接口决定：VideoRequest仅expected_version/shot_key/profile/idempotency_key；输入由数据库当前确认版本及已选首帧生成。VideoRuntime(store, adapters=None, files=None)，create/list/cancel/abandon/select/run_once，并提供recover_poll显式恢复查询。adapters白名单为空则拒绝排队。files须显式validated_video=True且提供实际校验put；缺失时在调用供应商前失败，默认无生产视频校验器。

状态：queued→submitting→submitted→polling；查询pending/暂时错误回submitted并限频；成功/失败终止。提交异常未知绝不自动重提。提交返回external_id先入库，后续worker轮次才查询。polling恢复更换claim_id，晚返回不能覆盖新状态；submitting只允许人工unknown。首帧与输入固定；成功输出暂存运行表JSON，不入正式media表。

测试先行，计划覆盖幂等、未知、查询恢复、旧版、权限隔离与拒绝伪造视频。独立临时PG数据库仅由已有fixture创建/删除。

## 实现与阶段验证

已新增 video_runtime_schema.py、冻结 migrations/versions/0009_video_runs.py、video_runtime.py 和 tests/test_video_runtime.py；未改共享 models/API/UI。VideoRequest 禁止客户端提交 packet/首帧。数据库约束固定首帧归属/镜号/版本与外键，触发器限制转换、保护终态和输入、external_id 一经持久化不得改写；选用记录只追加。

create 在项目锁内处理幂等、100次累计上限与活动镜头冲突，确认注册适配器/首帧能力/时长/无文本参数；由服务读取首帧而非信任请求。worker领取使用 SKIP LOCKED，每次提交只调用一次submit；持久化external_id后，另一次worker调用poll。next_poll_at默认30秒；查询失败仅重查原任务。恢复polling的旧claim结果不能覆盖后续查询；没有自动提交中断恢复。

实际首帧来自安全图片存储，提交前检查完整图片解码、字节数和SHA256，并复核当前首帧选用；无validated_video=True的注入校验器则提交前failed。运行时没有默认视频输出校验器，也没有默认视频供应商。输出仅放video_runs.output，白名单字段过滤本机路径与日志；仅保存受控存储标识、checksum、大小、媒体类型及正整数宽高/时长。

红测：初次因模块缺失收集失败；首轮隔离PG出现6项失败，定位JSONB None被写成JSON null导致ck_video_output约束失败，schema与冻结迁移同步none_as_null=True后11项通过。随后补充成功选用/终态不可改、预算、并发提交与人工放弃、恢复查询阻止旧claim覆盖，最终15项全通过。

验证命令：通过Python设置TEST_DATABASE_URL为本机测试服务器连接（不输出凭证），pytest tests/test_video_runtime.py -q --tb=short。fixture每项创建随机fp_test_数据库并销毁；未迁移或写入业务库。最终15 passed，16.31秒；现有Starlette/AnyIO弃用警告1项。git diff --check仅本任务文件通过。

测试边界：RejectingFiles拒绝伪造视频；成功链路使用显式ContractOnlySink测试替身，只证明数据库编排与选用行为。没有实际视频生成、解码、播放或画质/音轨验收。主任务获知无生产供应商/校验器，默认UI仅历史及恢复操作，不展示可真实执行承诺。

交接：接口list返回runs/selections/max_runs，run包含id/version/shot_key/status/error/external_id/selected/applicable。主任务负责注册表、API、worker入口和UI；本子任务文件均在共享主目录，未提交。未来接入需实际供应商能力校验及有界真实视频解码存储器，人工复核输出。迁移仅在随机测试库验证，业务迁移待主任务按授权执行。

# 火山方舟图片与视频

2026-10-26：已接入 Seedream 单图文生图与 Seedance 2.x 单首帧视频。接入、恢复和媒体校验经过模拟 HTTP、隔离 PostgreSQL 与真实浏览器测试；尚未用真实火山账户生成，不能据此判断画质、声音效果或账户权限。

## 配置与启动

在已有本机 `.env` 中追加 `ARK_API_KEY=你的密钥`，不要覆盖原文件或提交密钥。Web、图片 worker 和视频 worker 必须读取同一份环境配置、数据库和媒体目录。此轮无数据库表结构迁移；已有工程仍应使用当前迁移版本。

在项目目录分别启动三个终端：

```powershell
# 终端一：网页
.\start.ps1

# 终端二：处理已排队的图片
.\.venv\Scripts\python.exe -m scripts.media_worker

# 终端三：提交和查询已排队的视频
.\.venv\Scripts\python.exe -m scripts.video_worker
```

`--once` 仅处理一个当前可执行步骤：视频通常先提交，至少30秒后下一次执行才查询。持续 worker 会自行间隔查询。只启动网页不会执行生成队列；启动 worker 会处理已有排队任务，可能产生费用。修改密钥后重启相关进程。

工作台操作：

1. 保存并人工确认分镜；进入“图片素材”，添加火山 Seedream 配置。复制控制台中已开通模型的**完整 Model ID**，密钥环境变量名填写 `ARK_API_KEY`。
2. 预览本镜首帧提示词，核对尺寸后生成。刷新查看，人工选用首帧。
3. 进入“视频与检查”，添加 Seedance 配置，选择分辨率及是否生成声音。保存配置不调用模型。
4. 核对镜号、版本、时长、模型与声音选项，明确勾选本次生成后提交。刷新查看视频候选，播放核对后人工选用，再进入检查或后期。

## 已支持与边界

- 官方北京区域地址固定为 `https://ark.cn-beijing.volces.com/api/v3`；通用兼容图片接口仍保留为独立适配器。文字模型配置保持独立。
- 图片：完整 Seedream 4.0、4.5、5.0 Pro / Flash / Lite Model ID；单张静态图片、base64 返回，本地解码后入库。暂不接参考图编辑、组图、图层拆分与流式输出。
- 尺寸：按已读文档的型号限制在提交前校验。4.5 / 5.0 Lite 采用至少3686400像素；5.0 Pro / Flash 上限4624220像素。切换配置时给出尺寸建议，提交不静默改变用户填写的尺寸。
- 视频：Seedance 2.0 系列及2.5，单首帧，时长为整秒；2.0 为4–15秒，2.5 为4–30秒。不会自动取整、更改分镜或选择不确定时长。
- 视频默认720p、无声、保留水印。分镜有对白或声音要求而配置为无声时拒绝提交，需显式开启声音或先修订分镜。声音效果仍需人工核验。
- 480p / 720p 可选；1080p 仅开放2.0标准版。2.5的1080p采用HEVC，而当前媒体验收和浏览器链路限定H.264，因此在付费提交前拒绝。4K未开放。
- 首帧本地限定静态PNG/JPEG/WebP、20MiB以内、各边300–6000像素、宽高比0.4–2.5。该20MiB是本项目既有上限，较供应商限制保守。
- 不解析 `ep-...` Endpoint ID，因为无法从编号判断实际模型能力；暂不自动回退型号。以后可增加显式能力映射。
- API接入不等于已开通模型。实际服务地区、权限、余额条件和价格以用户控制台为准，不自动开通、充值或购买资源包。

## 请求与恢复

图片和视频均使用现有持久化账本及幂等键。视频先记录提交状态，再单次POST；取得外部任务ID后落库，后续只GET查询原任务。提交超时/响应损坏标为结果未知，不自动重新生成。查询与下载的临时故障可重查原任务；明确失败、无效输出等保留终态。

网页响应丢失时，原请求参数及编号存于当前浏览器会话，用户点击核对恢复；刷新记录发现同一编号后清除待恢复状态。浏览器会话存储被用户清空时，先查看数据库中的运行记录，不直接重建付费意图。

成功结果立即下载，当前仅接受官方北京区域TOS HTTPS域名，禁止跳转，下载不携带Ark密钥、客户端认证或Cookie。最多256MiB；本地实际解码和校验和检查通过才接纳。签名下载地址不进入公开账本；外部任务ID保留供人工核对。

官方视频URL有效期24小时、任务仅保留最近7天可查；请及时运行 worker。播放器能播放不代表内容质量通过，不新增自动语义审核。

## 来源与验证

来自资料库 S018；核对日期2026-10-26。采用原生参数、任务状态和媒体限制，没有照搬外部项目实现。

- [图片生成API](https://console.volcengine.com/ark/region:cn-beijing/docs/image-generation-api)：size、response_format、sequential_image_generation、返回数据。
- [创建视频任务](https://console.volcengine.com/ark/region:cn-beijing/docs/create-video-generation-task-api)：first_frame、duration、resolution、generate_audio、output_format。
- [查询视频任务](https://console.volcengine.com/ark/region:cn-beijing/docs/get-video-generation-task-api)：状态、content.video_url、有效期与TOS地址示例。
- [模型列表](https://console.volcengine.com/ark/region:cn-beijing/docs/model-list)：完整Model ID与型号范围。浮动文档在扩展型号前需复核。

测试入口：`tests/test_ark_adapters.py`、`tests/test_ark_integration.py`、`tests/ark-workbench.test.cjs`。具体运行证据与局限见[任务足迹](devlog/2026-10-26-volcengine-ark-01a151.md)。首次真实试片建议只提交一个短镜头，核对火山账单与结果后再批量制作。

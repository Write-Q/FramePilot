# 分镜图片与视频输入

当前使用需迁移至0010；新增[视频检查与人工审核](video-inspection.md)。下文0008/0009说明保留对应阶段，最新数据库状态以迁移及运维足迹为准。

2026-10-23视频运行时新增：独立视频任务表与submit/poll执行流程，保存外部任务编号后才进行查询；支持查询中断恢复、候选选用和只读任务历史。已接入本地视频解码存储和候选播放器；供应商仍未配置，默认注册表为空，不开放真实生成。接口说明见本文末。

当前实现：确认分镜 → 静态帧提示词预览/修改 → 图片任务排队 → 独立worker生成 → 候选预览 → 人工选用 → 视频输入预览。图像接口是兼容Images API的明确子集，尚未选定真实供应商或验证生成质量。

## 视频任务底座

0009新增fp_video_runs和fp_video_selections，保留原0008图片表。POST/GET `/api/production/projects/{project}/storyboards/{board}/video-runs` 创建/读取任务，POST其`{run}/cancel|abandon|recover-poll|select`处理状态。默认未注册供应商时创建被拒；仅宿主显式注册VideoAdapter并提供实际视频验证存储后可以执行，不根据模型名字猜测协议。

状态为queued→submitting→submitted→polling；pending或查询错误按间隔回submitted，成功/失败/unknown终态保留。提交超时不重提；polling中断可以recover-poll，仅查询原外部ID。claim_id隔离恢复前后的晚到响应。独立宿主通过scripts.video_worker.work(runtime)启动，直接运行脚本会说明尚未配置，不会调用外部服务。

输出只由验证存储返回安全storage_key、checksum、大小、真实宽高和时长元数据；已新增PyAV实际解码存储、限定项目归属的媒体读取URL及原生播放器，支持HTTP Range。测试中的ContractOnlySink只验证数据库成功/选用链路，不能证明输出视频可播放。真实视频生成、视频语义审核和剪辑仍待后续接入。

## 使用

先按数据库说明备份并显式迁移至当前 `0009_video_runs`。安装更新后的requirements-lock.txt（新增Pillow图片解码校验）。Web应用启动不会自动迁移或启动生成worker。

在分镜工作台保存并确认当前版本，选择镜头及首帧/关键帧/尾帧，预览对应静态描述。可以修改本次执行提示词，修改不会改写已确认分镜；缺少对应静态描述时先补充，程序不会根据完整动作猜起始画面。

在“图像配置”中填写API基础地址、型号及密钥环境变量名称，例如 `STORYBOARD_IMAGE_API_KEY`。密钥值保留在本机环境或.env中。图像配置不接受文本temperature、seed、max_tokens或思考等级，避免无效透传。分辨率需由所选服务实际支持；画幅文字与尺寸都应在提交前检查。

在同一项目、同一数据库和环境中另开终端运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.media_worker
# 或只领取至多一个已排队任务
.\.venv\Scripts\python.exe -m scripts.media_worker --once
```

worker启动会处理已明确提交的队列任务，可能产生所配服务的费用。未启动时任务保持排队；Web刷新不会重新提交。当前每项目累计最多100次图片请求（含失败、取消），同版同镜头同帧一次只允许一个排队/运行任务。

图片默认保存在项目 `data/media`，数据库保存路径标识、校验和、实际宽高及来源。可通过 `FRAMEPILOT_MEDIA_ROOT` 指定持久化目录，Web与worker必须一致，备份时数据库和媒体目录一起保留。任务完成只表示生成并解码成功，不代表人物、构图或专业质量合格。候选需人工选用，不能自动成为视频首帧。

## 接口边界

- 图片执行器 `openai_images`：POST `{base_url}/images/generations`，字段model/prompt/n=1/size；仅接受一张base64图片。暂不接URL输出、参考图编辑或批量返回，不自动下载模型给出的URL。
- 文件：仅静态PNG/JPEG/WebP，真实解码、20MiB文件上限和2500万像素上限。文件用随机标识不可覆盖创建，通过限定项目的接口读取，不向前端返回本机路径。
- 任务：queued → running → succeeded/failed/unknown；仅queued可取消。超时或连接故障保留unknown，不能假定没有计费。进程硬退出可能停在running，人工核对后标记未知；不会自动重新付费提交。
- 并发：数据库领取使用行锁和SKIP LOCKED；同一任务只由一个worker领取。标记未知后晚到结果不会恢复终态；文件写入与数据库提交之间中断可能留下未关联文件，当前不自动删除。
- 版本：绑定分镜、镜号、角色、提示词及模型配置的固定版本。新版不继承旧图选用；旧图仍可查看。队列开始执行前检查来源是否仍有效，过期则不调用模型。
- 视频：`video-input`仅预览同版本已选首帧、显式视频提示词和时长；有对白/声音会标注需要音频能力核对。Python适配协议区分submit和poll，测试使用模拟供应商；已有外部ID持久化运行器和视频解码验证；尚无具体供应商HTTP实现；本地剪辑/成片见[后期说明](postproduction.md)。未选服务前不提供伪装成可用的生成按钮。

接口位于 `/api/production/projects/{project}/storyboards/{board}` 下：GET `frame-prompt`、POST/GET `media-runs`、POST `media-runs/{run}/select|cancel|abandon`、GET `video-input`。媒体读取为GET `/api/production/projects/{project}/media/{media}`。请求和历史通过幂等键对账。

## 采用来源与验证

按本地资料库R003/R006/R010/R018定位。已读固定Toonflow提交的 [imagePromptCraft](https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/skills/v118workflow/references/knowledge/imagePromptCraft.md) 与 [storyboardImages](https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/skills/v118workflow/references/storyboardImages.md)，适配单帧时态、候选/选用分离和逐镜版本追溯。Jellyfish的首/尾/关键帧关注点用于输入区分，精确定位见frame_prompt.py的SOURCES。

视频输入采用同一固定提交的videoPromptCraft/videoProduction相关段落，准确位置写入video_input.py manifest；没有搬用其画布工具或模型专属参数。[官方Images API](https://developers.openai.com/api/reference/resources/images/methods/generate)只用于本次协议核对，不代表已验证任何账户。

工程测试、真实浏览器、真实模型效果必须分别看待。当前图片/视频均未做真实模型调用；测试图片是程序生成的固定图案。开发证据见[本轮足迹](devlog/2026-10-22-shot-media-01a151.md)。

## 视频文件验证与预览（2026-10-23）

新增av==19.0.2，worker在30秒时限的独立子进程完整解码，输入为内存字节，限定MP4/H.264或WebM/VP8/VP9，不允许外部资源；限制256MiB、2500万像素、600秒与100000解码帧。校验失败不保存候选。当前是技术检查，不是视觉、台词或口型审核；浏览器/设备的具体编码支持仍有差异。

默认目录data/video，可用FRAMEPILOT_VIDEO_ROOT覆盖，Web与worker必须相同。媒体接口为video-runs/{run}/media，核对项目归属、文件大小和checksum后才响应，支持Range；播放器不自动播放。页面展示实际宽高/时长和计划差异，并由用户选用。无新迁移，业务库保持0009。

测试使用本地PyAV编码短MP4，经过模拟供应商回传、实际解码、隔离数据库、HTTP及Edge播放器；没有调用真实生成供应商。解码原生库仍应随依赖更新维护，子进程时间/数量限制不等于操作系统级内存沙箱。

# 视频输入与供应商协议契约

方向：用户未选视频服务，本子任务只实现当前确认分镜与已选首帧的输入组包、submit/poll 分离的 Python 协议。不实现 HTTP、不抓取 URL、不把 mock 返回当视频生成。

按本地资料入口直达 Toonflow 固定提交 d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d，读取 references/knowledge/videoPromptCraft.md 与 references/videoProduction.md。采用真实输入、保留既定时长/动态/对白、无默认模型和明确验收边界；不套用特定供应商或旧版15秒限制。

开始测试：先编写输入过期/角色/选用状态/动作缺失与协议返回组合测试，再实现。范围仅 video_input.py、test_video_input.py 及本足迹。未提交，由整合任务接入预览 API。

## 完成与验证

- build_video_input 必须读取当前有效确认分镜，同版本/同镜号/first/成功且 selected=True 的真实首帧记录；拒绝来源失效、版本过期、错误角色和未选图片。若输入带项目/kind，也检查其一致性。此函数依赖整合层已做用户/项目授权，不能代替数据库权限校验。
- 原样保留分镜 duration_ms，video_prompt 必填；不把静态图或 action 自行推演为视频动作。显式 camera_motion 未出现在 video_prompt 时才附加；保留已有风格、结构化对白（优先于旧 dialogue 字段）或旧对白、声音。没有音频信息不自行加“无声”要求。有音频信息标识 requires_audio_capability，具体供应商需后续能力校验，不宣称具备声音生成能力。
- manifest 固定规则/来源版本、分镜版本/镜号、首帧媒体及运行 ID、输入及提示词哈希；不复制供应商/首帧原始 manifest。仅表示输入契约通过，供应商及媒体内容仍待验证。
- VideoAdapter 为 Protocol，仅声明 submit(config, packet, first_frame: bytes) 与 poll(config, external_id)。VideoSubmission 要求有效外部标识；VideoPoll 限 pending/succeeded/failed，成功必须非空 bytes + video/mp4 或 video/webm，非成功不得输出媒体。类型检查不验证视频解码、时长、画质和声音。
- 固定原文定位已放 SOURCES：videoPromptCraft.md 第3—25、136—147行，videoProduction.md 第6—18、22—44行。仅采用通用准备/状态/验收边界，未采用供应商特定模板或伪造首尾帧能力。

红测先观察 video_input 模块不存在导致收集失败，实现后首次29项通过；补充项目隔离、防音频臆造、旧对白/风格及错误信息测试。mock 提交一次后分别查询 pending/succeeded，仅是契约样例，没有生产模拟执行器。

最终命令 `.venv/Scripts/python.exe -m pytest tests/test_video_input.py -q`：34 passed，0.29秒。`git diff --check`（仅本任务三文件）通过。

交接：无具体服务配置，因此实际视频提交、轮询持久化和视频文件验收尚未实现。整合任务当前环境无 ffmpeg/ffprobe，不能称媒体生成或验证完成；后续供应商适配必须限制响应大小、清洗错误、先保存 external_id 后查询，并用真实媒体工具检验结果。只增加本模块、本测试与本足迹，未提交，等待整合 API 预览。

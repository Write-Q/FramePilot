# 真实模型接入前的成片闭环

用户已授权持续实施并按阶段归档。提供模型无关的可导出第一版，模拟供应商素材不冒充真实AI质量验证。

## 约定

时间线按项目/分镜系列/固定版本保存不可变版本，clips=[{run_id,start_ms,end_ms,gain}]，subtitles=[{start_ms,end_ms,text}]，audio_tracks=[{asset_id,offset_ms,gain,loop}]，preset landscape/portrait/square映射1280x720/720x1280/720x720，fps24；原声默认gain1。仅已选用、同项目当前确认版本的成功视频可首次加入；旧时间线保留但过期不可新导出。

clip最多30，单clip不少于200ms、裁切范围不超过真实时长，总长<=600秒；字幕最多100，每条<=200字、区间在总长内；音频轨最多4，offset非负且在总长内，gain0..2，不会调用外部TTS；音乐loop可选。hardcut为首版衔接，不添加未经用户选择的转场。

## 子系统

1. 本地渲染器editing_render.py：显式文件与受控参数输入，FFmpeg参数列表无shell，trim/concat、scale/pad/fps、原声与外音频amix/alimiter、ASS字幕，真实输出解码后VideoFiles不可覆盖落盘。工具/字体缺失明确失败，不静默丢音轨或字幕。
2. editing_contracts/schema/service及0011：时间线版本、音频资产、导出任务queued/running/succeeded/failed/unknown。输入manifest固定视频checksum和音频checksum；独立worker领取SKIP LOCKED，持久化终态，中断不自动重渲染；幂等、版本/项目隔离。音频上传限20MiB/600秒，仅实际可解码WAV，使用raw body流避免新增multipart，UUID路径，无任意路径输入。
3. HTTP /projects/{project}/storyboards/{board}/editing：GET当前和历史timeline，POST保存timeline(expected_version乐观锁，source_version为分镜当前版本)，POST/GET audio，POST/GET exports，GET exports/{id}/media或download。POST exports/{id}/abandon标记中断。POST exports/{id}/accept记录人工成片验收，不把渲染成功等同交付合格。
4. 独立后期页面/editing?project=&board=，载入已选片建立初始时间线，逐行排序/裁切/增益，字幕和音轨本地配置，保存/导出/预览/下载/验收，旧版只读与错误恢复。模型接入前允许本地视频上传为明确“本地素材”候选并人工选用，来源不得标AI生成。
5. 模拟端到端测试包含多镜拼接、不同尺寸归一、无声/有声、配音+BGM、字幕、区间非法、损坏素材、跨项目、重启恢复/幂等、过期时间线与导出下载；真实浏览器与成片实际解码。完成阶段验证/备份演练/迁移/提交推送，最后出接入模型前验收清单。

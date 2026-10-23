# 本地后期渲染器（01a151）

## 需求与约定

- 关联主任务：[真实模型接入前后期闭环](2026-10-23-postproduction-01a151.md) 与 [实施计划](../superpowers/plans/2026-10-23-postproduction-01a151.md)。
- 主任务分工：本记录只拥有 `app/production/editing_render.py`、`tests/test_editing_render.py`；由主任务集中整合提交和推送，本子任务未单独提交。
- 接口：`render_timeline(timeline, clips, audio, *, timeout=120) -> bytes`；clip 为本地 `Path/start_ms/end_ms/gain`，audio 为本地 `Path/offset_ms/gain/loop`；失败抛出不包含私有路径的 `EditingRenderError(ValueError)`。
- 输入路径必须由服务端受控存储解析与校验 checksum，禁止直接传 HTTP 用户路径；持久化及完整视频解码由主任务的 `VideoFiles` 边界承担。

## 实际实现

- landscape 1280×720、portrait 720×1280、square 720×720，24fps；H.264 MP4 或 VP8/VP9 WebM 受控解封装输入，统一为 H.264/AAC MP4。
- trim、时间戳归零、等比 scale/pad、hard cut concat；保留原声并支持各镜头 0–2 gain，无声镜头补 48kHz stereo silence。
- 最多 4 个 PCM WAV 加轨，offset、独立 gain、可选循环；`amix normalize=0` 后 `alimiter` 并补偿 lookahead 延迟。
- ASS 字幕文本写固定相对文件，不拼入滤镜；用户反斜杠和花括号转全角字面字符以阻断 ASS override。检测 FFmpeg 滤镜/编码器和中文字体，缺失时明确失败。当前 Windows 微软雅黑实际存在。
- 子进程参数列表，无 shell；输入快照存私有临时目录，固定相对文件名、强制 demuxer、限制协议；输入大小、总时长、条目数、数值和文本边界；输出最多 256MiB，临时目录自动回收。

## 来源及适用核对

实际读取 [FFmpeg n7.1 filters.texi](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n7.1/doc/filters.texi) 的 concat、amix、ass、alimiter 章节。按照 concat 的时间戳归零和统一参数条件、amix 的 float sample / duration first / normalize 条件、ASS 文件输入和 limiter 延迟补偿要求适配。实际本机 FFmpeg 7.1 capabilities 命令确认 `concat/amix/alimiter/ass`，非仅根据文档推断。

## 验证与问题

- TDD：先执行缺失实现测试，补最小接口后观察实际 `NotImplementedError` 失败；随后实现并迭代。WebM 支持、缺失路径、超大整数边界均先观察对应失败再修复。
- 真实测试发现 FFmpeg 7.1 在 `scale -> fps` 顺序时，0.5 秒 12 帧素材仅产出 11 帧；最小滤镜命令复现并定位到 EOF 帧时长传递，改为 `fps -> scale` 后恢复 12 帧。
- 验证命令（工作区 TEMP 与专属 pytest basetemp）：`.venv/Scripts/python.exe -m pytest tests/test_editing_render.py -q --basetemp=.tmp-render/pytest-evidence`，结果 **28 passed in 4.76s**。
- 测试实际创建本地 H.264/VP9/WAV、调用 FFmpeg、用 PyAV 解码输出；覆盖两镜不同尺寸拼接、横/竖/方输出、原声及 gain=0、WAV offset/loop/nonloop、4 轨限幅、48kHz stereo、中文字幕在激活时段的图像差异、ASS override 字面化、损坏媒体、libass 缺失、超时及进程错误脱敏、参数集合上限。
- 测试不调用真实模型，不能代表 AI 视频语义质量；未验证最大 600 秒任务的实际耗时/画质。超时为每次有界子进程的超时，服务端仍需持久化失败/中断终态。

## 交接

- 主任务继续：服务层调用、路由与 worker、前端交互、完整流程解码/验收、归档提交推送。
- 本子任务工作文件如上，相关独立记录须随功能一起归档；本次专属 `.tmp-render` 仅用于测试临时媒体，交接前删除，不保留大媒体。

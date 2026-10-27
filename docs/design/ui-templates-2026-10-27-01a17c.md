# FramePilot UI 模板提案

设计阶段：方向比较，未获生产实施批准。来源足迹：[UI 模板探索](../devlog/2026-10-27-ui-templates-01a17c.md)。

## 最新审美选择

第一轮三套预览未达到用户预期，保留为探索记录。用户随后选择 [Craft](https://www.craft.do/zh-CN) 的色彩和画面表现，以及 [FLORA](https://flora.ai/product-canvas) 与 [Linear](https://linear.app/) 的界面质感。

下一版建议采用柔和的浅色创作空间、充分的图像展示与精细的工具界面层级；重点处理字体、间距、边界、浮层和操作反馈。具体配色与构图仍属 AI 待验证建议。用户尚未批准旧模板布局或生产实现，也未要求照搬 FLORA/Linear 的深色主题。

下一轮应先给出完整分镜主界面的高保真视觉预览，验证这一融合方向。下文三套旧模板不代表最新选定设计。

打开同目录 `ui-templates-2026-10-27-01a17c.html` 可切换三套模板；生成的独立包装使用可视化技能的运行时，首次加载部分运行时资源需要联网。画面数据已经内嵌，不访问项目 API。

| 模板 | 核心布局 | 适用任务 | 取舍 |
| --- | --- | --- | --- |
| 制作工作台 | 左侧助手，右侧常驻镜头列表与单镜编辑 | 连续制作、逐镜调整，作为全局布局候选 | 多栏对小屏较拥挤，需要重排 |
| 分镜画廊 | 左侧助手，右侧帧画面网格，选中后显示详情 | 对比构图、检查一组镜头的节奏 | 精细参数不宜全部常驻 |
| 导演审片台 | 左侧助手，大画面与侧边参数，下方镜头序列 | 检查首帧、视频候选与剪辑结果 | 深色适合画面检查，长文本编辑需另行适配 |

AI 建议以第一套统一框架，第二、三套作为专用视图。该建议不代表用户决定。五个板块的实际名称本轮未确定；预览沿用项目已存在的编剧、分镜、剪辑导航，没有擅自建立五个新页面。

## 示例素材与来源

- 示例项目“最后一朵花”、四镜内容与助手回复均为本轮构造的设计演示。
- 单张温室机器人概念图通过内置 image_gen 工具生成，并为内嵌展示压缩为 JPEG；不同缩略图为同图裁切，不代表独立镜头或多次模型生成效果。
- 原图文件名：`exec-c21ce664-d5bc-4985-a6e9-47f9ec599dab.png`。来源为本聊天 `generated_images/01a17cd4-536a-7462-a62d-0c795b405cce`，压缩副本已嵌入预览，不依赖原图路径。
- 生成提示词：Generate one cinematic reference frame for a fictional storyboard UI concept, landscape 16:9. A small weathered orange service robot stands at the right third in an abandoned overgrown greenhouse, discovering a single tiny bright white flower amid moss. Wide shot, lush deep teal foliage, warm afternoon sunlight pouring through broken glass roof, photorealistic practical miniature look, thoughtful restrained science fiction, layered depth, subtle film texture, rich photographic contrast. No words, lettering, UI, borders, montage, or logos. This is illustrative sample content, not a real project output.

## 验证边界

- 1024/390/320 像素宽度的三套模板，图片、切镜、确认反馈及横向溢出检查共 9 组通过。详情见同目录 verification.json 文件。
- 脚本语法检查通过。确认、发送、建议预览均为本地示例逻辑，没有与项目 API 对接；未验证模型质量、真实视频播放或生产工作流。
- 未改动任何 app/static 生产文件。用户选定后再形成对应页面设计与实施计划。

# 分镜专业规则与参考映射

日期：2026-10-19。用户要求实际阅读参考项目的提示词和skill，并补充专业资料。本文为静态调研及FramePilot适配建议，不是生成质量验证，也不是将外部skill安装到本项目执行。

## 固定来源

Toonflow当前提交：`d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d`，通过GitHub仓库树API获取。旧`data/skills`已不在当前树，旧链接出现404，按该路径查询的当前历史列表为空；因此不能将搜索引擎缓存当成当前实现。现已实际读取：

- T1：[shotCraft.md](https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/skills/v118workflow/references/knowledge/shotCraft.md)：镜头信息目的、表演、构图、空间、计时和审阅方法。
- T2：[videoPromptCraft.md](https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/skills/v118workflow/references/knowledge/videoPromptCraft.md)：按实际模型输入模式组织提示词，区分媒体引用与文字标签。
- T3：[directorPlan.md](https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/skills/v118workflow/references/directorPlan.md)：先确定场次、表演和制作约束，再进入镜头制作。
- T4：[分镜skill](https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/teams/storyboardTeam/skills/storyboard/SKILL.md)及[连续性知识](https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/teams/storyboardTeam/knowledge/continuity.md)：镜头服务叙事，区分事实、补充、待确认项与实际媒体状态。

Jellyfish沿用此前固定提交`a9678194ddf2d9be3ccbe78d4287d87d5089e123`：

- J1：[shot_frame_prompt_agents.py](https://github.com/Forget-C/Jellyfish/blob/a9678194ddf2d9be3ccbe78d4287d87d5089e123/backend/app/chains/agents/shot_frame_prompt_agents.py)：首帧、关键帧与尾帧分别组织；上下文包含相邻镜头、动作阶段与参考实体。
- J2：[shot_video_prompt_pack.py](https://github.com/Forget-C/Jellyfish/blob/a9678194ddf2d9be3ccbe78d4287d87d5089e123/backend/app/services/studio/shot_video_prompt_pack.py)：将动作、构图、空间、对白及参考关系传递到实际视频提示词。
- 此次`script_divider_agent.py`获取失败，没有将其记为重新核对成功。

外部第一方资料：G1 [Google视频提示词指南](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/video-gen-prompt-guide)，已读主体、动作、场景、机位、运动段落。该资料有助于描述模型输入，并非所有模型的共同能力承诺；部分复杂视角也明确需要实际测试。

## 提炼与当前落点

下列为FramePilot自己的适配，不复制外部整套prompt或其执行流程。

| 规则 | 依据 | 本轮落点 |
| --- | --- | --- |
| 每镜说明新信息或叙事作用，避免仅写抽象情绪 | T1、T4 | `Shot.purpose/action`；语义质量由后续审核与人判断 |
| 场戏与镜头分别记录，来源固定到正文版本 | T3 | 拆解、场戏、分镜与镜头落既有领域表 |
| 景别、机位、摄像机运动分开 | T1、G1 | `shot_size/camera_angle/camera_motion`，不把俯拍当运动 |
| 明确构图与人物画面方向 | T1、J2 | `composition/screen_direction`；不声称已自动验证180度空间关系 |
| 时间中的动作过程与某一瞬间的画面分开 | J1、J2 | `action_beats/frame_prompts/video_prompt`；首、关键、尾帧独立 |
| 起始状态与结束状态可交接 | T4、J1 | `state_start/state_end/continuity_notes` |
| 视觉风格与照明继承已确认输入 | T2 | `visual_style/lighting`，不默认创造新光照事实 |
| 镜头规划时长与模型可选时长是两种约束 | T2、G1 | 毫秒整数；顺序节拍已填时长合计不得超出镜头，执行阶段再校验供应商范围 |
| 参考图必须真正进入请求，文字地址不能冒充图片输入 | T2 | 尚待媒体与供应商适配器落实，本轮不声称已接通 |
| 状态与证据不能混淆 | T4 | 手工分镜标记`creation_method=manual`，不评价不存在视频的画质 |

## 不照搬的模板规则

一镜一个主要运镜、片段最大15秒、固定字速、默认不加音乐等均有来源项目/模型/流程前提。FramePilot不将这些数字写成普适硬约束。对白容量先作为规划提醒，后续以真实配音时长与人工审阅验收；动作时长之和只是可计算检查，不能证明真实动作可拍。

Toonflow新版参考文件自身记录了旧规则冲突，例如光影描述、跨场过渡与动作跨片段处理。当前采用原则：明确的用户要求及已确认剧本/资产 → 本镜叙事与连续性 → 经核实的供应商能力 → 选用模板；冲突应展示问题，而不是机械删词或套固定镜头数量。

## 后续专业工作与验收样例

AI分镜节点接入前，将规划/分镜/静态帧/视频运动/审核分别组织输入，传入确切版本及必要上下文，不把全部skill无差别塞进一个提示词。需要保存提示词版本、来源规则和模型配置版本。

首批人工标注案例包括：交接钥匙保持持物手与归属；对话反打保持视线关系；悬疑线索在画面可识别；多动作短镜头能提出拆分；首帧不提前出现完成态；画面人物不误对画外旁白口型；有意跨轴与换场不被机械误报。当前仅落实数据容器和确定性校验，尚未实现或验证这些语义评测、真实图像和视频效果。

来源足迹：`../devlog/2026-10-19-production-foundation-01a151.md`。未复制第三方实现；若后续复用代码或完整模板，另核对对应版本许可证。

## 补充：更适合专业知识层的来源

用户追问是否还有更合适的专业技能来源。本次进一步查阅下列第一方教学/产品资料；仅作来源筛选与局部阅读，不声称已完成全部课程或将内容实现为Agent技能。

| 来源 | 已核对的入口与内容 | 建议用途 |
| --- | --- | --- |
| StudioBinder | [Storyboard Rules](https://www.studiobinder.com/blog/storyboard-rules/)讨论分镜可读性、镜头/画格区别及连续性；另有[分镜与镜头表教程](https://www.studiobinder.com/tutorials/visualize/) | 分镜交付字段、镜头信息目的与审阅清单 |
| StoryboardArt | [180度与画面方向教程](https://storyboardart.org/storyboard-tutorials/180-degree-rule-film/)；[讲师页](https://storyboardart.org/instructors/)说明实践型分镜教学背景 | 空间调度、方向与轴线相关案例，规则须保留有意突破的解释入口 |
| Learn About Film / Tom Barrance | [180度、视线与留白](https://learnaboutfilm.com/film-language/sequence/180-degree-rule/)提供图示，也说明重新建立空间关系的方法 | 将抽象连续性原则拆成可检查问题及正反案例 |
| Blackmagic Design官方训练 | [训练目录](https://www.blackmagicdesign.com/products/davinciresolve/training)有剪辑、音频、调色与交付课程、练习文件和训练书；本次核对目录说明，未下载或读完整训练书 | 后期剪辑的专业工作流和可复现实验，不要求项目改用Resolve |
| Runway官方 | [Camera Terms, Prompts & Examples](https://help.runwayml.com/hc/en-us/articles/47313504791059-Camera-Terms-Prompts-Examples)及[Gen-4指南](https://help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide)有模型对应的术语与输入建议 | 将镜头意图翻译为特定模型的执行描述，必须标注模型/版本 |

补充候选：[Pixar in a Box](https://www.khanacademy.org/pixar)目录可确认故事与Film grammar板块，具体分镜练习页此次未获取到可读正文，暂不据此提炼规则；[ARRI Academy](https://www.arri.com/en/learn/arri-academy)可作为后续摄影/照明深化入口，当前优先级低于分镜与后期基础。

建议知识层以专业教学为依据，项目层继续对照Toonflow/Jellyfish落实数据与流程，模型层按实际供应商指南编译提示词。后续每项内部技能应保存来源、适用条件、输入/输出、可计算检查、人工判断项、正反例和版本；当前只是架构建议，尚未创建或安装这些技能。

# Toonflow / Jellyfish 提示词与 Skill 补充盘点

核对日期：2026-10-19。用户指出两项目存在大量细化规则，此前只登记6个核心来源文件不足以表达其内容规模。本次重新获取固定提交的完整递归目录，两棵树均未截断；核对提示词定义、SQL模板行及部分文档结构。**目录覆盖不等于全部精读，定义存在不等于效果验证，现有分镜仍只接入3组本项目提示词。**

机器清单：[project-prompt-inventory.json](project-prompt-inventory.json)，共53个文件入口，保留固定版本、路径、链接、类别和核对程度。不复制完整第三方模板，不将仓库中的操作指令作为本会话指令执行。

## 数量口径

| 项目 | 已核对数量 | 说明 |
| --- | ---: | --- |
| Toonflow SKILL.md入口 | 5 | workflow、v118workflow、canvas、storyboardTeam的storyboard、MCP的toonflow；包括应用操作技能，并非全是分镜能力 |
| Toonflow references文档 | 31 | 分布在workflow/v118workflow/canvas，单文件可能含多个模板或方法 |
| Toonflow角色提示词 | 3 | 导演、分镜编写、分镜审阅 |
| Toonflow连续性知识文档 | 1 | storyboardTeam/knowledge/continuity.md，单列不混入references计数 |
| Jellyfish业务提示词模块 | 12 | 排除base.py、__init__.py、重导出文件、schema、路由和测试 |
| Jellyfish业务Agent类 / PromptTemplate对象 | 14 / 14 | 首帧、尾帧、关键帧分别一个对象，但共享基础模板；对象数不是完全独立的模板家族数 |
| Jellyfish SQL预置模板 | 6 | 演员正面、演员侧背、角色正面、道具、场景、服装 |

Jellyfish的`.cursor/skills/ui-ux-pro-max/SKILL.md`是开发UI技能，未计作影视业务Skill。原资料库60条来源是跨领域导航入口数；与本清单的文件数、模板数不是同一统计单位，不能相加冒充Skill总数。

## Toonflow：此前没有充分提炼的内容

固定提交：`d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d`。

- [workflow/SKILL.md](https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/skills/workflow/SKILL.md)：大型工作流，内嵌节拍、剧情保真、生成分段、时长、台词、参考绑定等规则；不能只读名称便算已完成提炼，也不能把特定模型规则当通则。
- [v118workflow/SKILL.md](https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/skills/v118workflow/SKILL.md)：分阶段入口；细节在它链接的references里。
- `storyboardTable.md`：文字分镜表与审阅；`storyboardPanel.md`：将已确认分镜落实为制作单元；`storyboardImages.md`：分镜图生成与验收。三个阶段不是同一提示词的三个别名。
- [imagePromptCraft.md](https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/skills/v118workflow/references/knowledge/imagePromptCraft.md)：分镜到单帧的字段映射，含Seedream中文参考模板和Nanobanana/Gemini结构化参考模板。需按实际模型版本另核能力。
- `assetDesign.md`：人物、场景、道具与变体、提示词示例；`visualStyles.md`：11种画风；`narrativeGenres.md`：叙事技法；`scriptCraft.md`：剧本方法。不是全部内容都已迁移到FramePilot。
- `workflow/references/methods/`：故事发展、改编、视觉设计、色彩与光照；`storyboardTeam/members/`：director、writer、reviewer三个角色分工。

31份references的全路径见JSON，避免仅凭少数示例再次漏掉目录。

## Jellyfish：提示词分散在代码和SQL里

固定提交：`a9678194ddf2d9be3ccbe78d4287d87d5089e123`。

[业务Agent目录](https://github.com/Forget-C/Jellyfish/tree/a9678194ddf2d9be3ccbe78d4287d87d5089e123/backend/app/chains/agents)已核对的14个提示词对象：

| 方向 | 对象/模块 |
| --- | --- |
| 剧本处理 | 简化、优化、拆分、元素提取、一致性检查 |
| 实体整理 | 实体合并、变体分析 |
| 视觉资产分析 | 人物肖像、服装、场景、道具 |
| 分镜帧 | 首帧、尾帧、关键帧 |

[001-init-prompt-template.sql](https://github.com/Forget-C/Jellyfish/blob/a9678194ddf2d9be3ccbe78d4287d87d5089e123/backend/sql/001-init-prompt-template.sql)还包含6条数据库预置生图提示词。此前检索侧重Markdown/Python，未把SQL种子作为模板来源，是明确遗漏。SQL是参考数据，未在本项目执行；其中参数、负面词与美学偏好不能不经适配直接套用。

已有`shot_video_prompt_pack.py`和相关schema/任务服务继续作为上下文与执行组织参考，不再按每个辅助文件增加“独立Skill”计数。

## 对当前实现的判断

当前K001—K003只是一版粗粒度组合，覆盖了规划、自检和静态帧的入口；尚未充分吸收分镜表/制作单元/分镜图验收、资产变体、模型专用模板和独立审阅分工。

后续应按业务阶段拆出输入输出和规则清单，映射到代码字段、模型调用、人工确认与评测案例；逐项标记“参考过/已改写/已接入/真实验证”。不以文件总数替代专业覆盖，更不能把本轮补盘点写成已完成所有模板迁移。

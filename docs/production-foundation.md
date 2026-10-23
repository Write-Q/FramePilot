# 第二版制作底座：模型配置与手工分镜 API

本段提供独立于编剧正文的制作数据流程。已实现模型配置的不可变版本、手工分镜创建/编辑/确认及来源有效性检查。后续已增加[分镜工作台](storyboard-workbench.md)、AI文字分镜和运行追溯，以及[图片队列、候选选用和视频输入预览](shot-media.md)。openai_chat和openai_images具有执行器，保存配置不代表供应商可用。视频实际生成、媒体审核与剪辑渲染尚未实现。

## 启用与验证

应用不会启动时自动升级表结构。使用新接口前，先停止写入并按[数据库基础说明](database-foundation.md)备份、演练，再显式运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.init_db
```

迁移0005新增模型配置、配置版本与分镜确认三张表；0006新增分镜运行记录，0007新增独立审核，0008新增图片任务和选用历史。复用现有场戏/分镜/镜头及媒体表，不改写编剧历史；业务库实际迁移状态以对应运维足迹为准。

启动后在`/docs`中找到“制作底座”标签。当前沿用本地单用户、单应用进程边界，不适用于公开多用户部署。

## 通用模型配置

`POST /api/production/model-profiles`示例：

```json
{
  "name": "分镜规划候选",
  "purpose": "text",
  "adapter": "openai_chat",
  "base_url": "https://example.test/v1",
  "model": "your-model-name",
  "api_key_env": "FRAMEPILOT_PLANNER_KEY",
  "timeout_seconds": 90,
  "parameters": {"temperature": 0.2, "max_tokens": 5000},
  "capabilities": {"image_input": false, "video_input": false}
}
```

地址与模型名均为示例。密钥实际值只在本机环境或忽略的`.env`设置，不提交API、不写入配置历史。`api_key_env`为空可表达无需密钥的本地服务。配置接口不解析环境变量；分镜执行时才读取。未知输入字段和值不会通过校验错误回显。

用途：`text/image/video/review/asr/tts`。同用途可保存多套配置，分镜按用途绑定确切配置版本；本段不设全局默认，也不自动切换现有编剧DeepSeek或游戏网关。

公共参数仅允许temperature/max_tokens/seed，不支持任意header、路径或HTTP请求体覆盖。能力字段是人工声明，`capabilities_verified=false`；后续由具体适配器验证，不能仅凭修改base_url适配全部供应商。

| 方法与路径（前缀`/api/production`） | 行为 |
| --- | --- |
| GET `/adapters` | 查询执行器实现状态，不访问外部服务、不验证具体网关能力 |
| GET `/model-profiles` | 列出每套配置当前版本 |
| GET `/model-profiles/{id}` | 读取当前配置 |
| GET `/model-profiles/{id}/versions/{n}` | 读取历史配置 |
| PUT `/model-profiles/{id}` | 请求`{"expected_version":1,"config":{完整配置}}`；创建新版本 |

更新旧版本返回409，不覆盖历史。用途属于配置身份，不能变更；需要新用途时创建另一配置。绑定旧版本不会随当前配置升级而变化。模型配置全局属于本机用户，不是项目私有资源。

## 剧本交接与分镜创建

先在原编剧工作台完成审核与确认。原稿直送的`ready_for_production`不是审核确认，本接口拒绝该入口；未确认稿和过期正文版本也返回409。

`POST /api/production/projects/{project_id}/storyboards`示例，所有引用须实际存在于该版剧本：

```json
{
  "source_version": 1,
  "content": {
    "schema_version": 1,
    "title": "钥匙交接",
    "aspect_ratio": "16:9",
    "visual_style": "已确认的写实风格",
    "scenes": [
      {"key": "scene-1", "title": "门前", "source_quote": "小禾把唯一的钥匙交给阿林。"}
    ],
    "shots": [
      {
        "key": "shot-1",
        "scene_key": "scene-1",
        "source_quote": "钥匙交给阿林",
        "purpose": "交代钥匙归属",
        "action": "小禾把钥匙递给阿林，阿林接住",
        "duration_ms": 4000,
        "shot_size": "中景",
        "camera_angle": "平视",
        "camera_motion": "固定",
        "composition": "小禾在左，阿林在右，交接动作可见",
        "screen_direction": "小禾向右看，阿林向左看",
        "lighting": "沿用已确认场景照明",
        "state_start": "钥匙在小禾手中",
        "state_end": "钥匙在阿林手中",
        "action_beats": [
          {"description": "递出钥匙", "duration_ms": 2000},
          {"description": "接住钥匙", "duration_ms": 2000}
        ],
        "frame_prompts": {"first": "钥匙仍由小禾持有", "last": "阿林已拿住钥匙"}
      }
    ],
    "bindings": {}
  }
}
```

可选绑定示例：`"bindings":{"text":{"profile_id":"创建配置返回的id","version":1}}`。支持多个用途，不允许引用不存在的版本或用途不匹配的配置。

每个场戏原文须逐字存在于固定剧本，每个镜头原文须逐字存在于其场戏原文。当前只验证文字来源存在，不证明分镜动作忠实、剧情全覆盖或时长真正可拍。动作节拍中的时长表示顺序规划；未填写的时长不估算，有填写的合计不能超过镜头时长。静态帧描述与视频运动提示词分开保存，填写尾帧不代表所选模型支持尾帧输入。

## 编辑、确认及历史

创建响应的`id`为该份固定场戏拆解/分镜系列ID，`version_id`为某个确切分镜版本ID。镜头`key`是由编辑方维护的稳定身份，每次修订的关系表行ID不同；重排时保留key，拆镜时为新增镜头分配新key。

| 方法与路径（前缀`/api/production/projects/{project_id}`） | 行为 |
| --- | --- |
| GET `/storyboards` | 列出每份分镜系列的最新版本 |
| GET `/storyboards/{id}` | 读取当前版本及来源状态 |
| GET `/storyboards/{id}/versions/{n}` | 读取历史版本 |
| POST `/storyboards/{id}/versions` | 请求`{"expected_version":1,"content":{完整内容}}`创建下一版 |
| POST `/storyboards/{id}/confirm` | 请求`{"expected_version":2}`确认当前版本，重复确认幂等 |

同一分镜系列固定场戏拆解，修订必须保留scenes，镜头可增删、重排或调整。需要改变场戏时从剧本新建另一份分镜系列。本段只支持旧编剧默认章节交接，不把兼容桥冒充完整多章节工作流。

新分镜不继承上一版确认。`confirmed`保存该版曾确认事实，`confirmation_effective`还要求来源当前且已确认；上游变化时历史不删，但有效性变为false。历史版本曾确认并不表示当前新版已确认，读取时须检查`version/current_version`，后续生成接口需明确选择有效版本和单独确认预算。

本段确认不授权付费调用。剪辑时间线尚未接入，后续应引用素材及确切分镜版本，不覆盖分镜顺序。

专业来源和适配取舍见[分镜skill调研](research/2026-10-19-storyboard-skills-01a151.md)。实施与验证证据见[本任务足迹](devlog/2026-10-19-production-foundation-01a151.md)。

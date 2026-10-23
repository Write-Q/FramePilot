# 图像协议、存储与静态提示词

任务：按已授权分镜媒体计划实现独立模块；服务未选，不运行真实模型。范围仅 media_io.py、frame_prompt.py 及对应测试。

决定：图像返回仅支持 base64 子集，不自动下载 URL；PNG/JPEG/WebP 必须实际解码校验，限制文件和像素，UUID 独立文件，拒绝越界路径。静态帧必须有对应 frame_prompts 或用户覆盖，不从完整运动动作猜画面。Pillow 当前缺失，已交整合任务添加依赖。

验证计划：先运行失败测试，再实现并重跑。测试不构成真实模型效果证据。未提交，后续由整合任务统一处理。

## 实现与证据

- 已新增 ImageResult、ImageAdapter 和 MediaFiles：只 POST 一次 images/generations；模型名由配置指定，不发送 response_format；无重定向、无自动重试、不下载 URL。timeout/5xx/408 标为 outcome_unknown；错误不回显服务正文。metadata 仅含解码所得宽高。
- 图片限制 20 MiB、2500 万像素、响应 28 MiB；Pillow verify 后重新 load 解码；只允许单帧 PNG/JPEG/WebP，MIME 必须相符。UUID 文件以 xb 独占创建，存储标识和 resolve 后路径双重校验。Pillow 13.0.0 已由整合任务加入依赖。
- 静态帧仅从对应 frame_prompts 编译；包含场景名、人物、风格与静态构图，不复制完整 action、camera_motion、对白和音效。明确 reference_images=[]，拒绝常见虚构图片编号占位符；这不是对任意自然语言的语义检测。
- 按整合反馈，prompt_override 是用户编辑后的完整执行提示词，原样去首尾空白使用，不重复包裹预览；可改变原帧意图，需要用户复核。manifest 保存规则版本、来源、哈希与帧定位。
- 配置中的文本采样/思考参数明确拒绝，避免静默忽略。size 接受 auto 或数字宽高，限制请求像素上限；不宣称尺寸已被具体供应商支持。

来源按本地索引直达固定原文读取：Toonflow d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d 的 imagePromptCraft.md 第10—41、100—111行及 storyboardImages.md 第12—47行；Jellyfish a9678194ddf2d9be3ccbe78d4287d87d5089e123 的 shot_frame_prompt_agents.py 中 _FRAME_FOCUS/_SHOT_FRAME_TEMPLATE 第105—124行。模块 SOURCES 保存完整定位。采用静态瞬间、实体名称、无虚构引用及候选图需验收原则；未照搬其模型专用模板与运镜字段。

先运行测试观察缺失模块导致收集失败；新增引用标记检查观察3项失败后实现；新增参数/尺寸检查观察4项失败后实现。初次执行默认 pytest 临时目录遇沙箱 ACL，改为项目内独立 basetemp 后通过。

最近验证：`.venv/Scripts/python.exe -m pytest tests/test_frame_prompt.py tests/test_media_io.py -q --basetemp=data/test-tmp-media-io-04`，42 passed。全部图像为 Pillow 固定像素样本，HTTP 用 MockTransport；未验证真实供应商模型生成质量。初始参数红测曾尝试保留 example.test 地址并连接失败，已改 MockTransport 且断言零请求，避免后续测试外联。

交接：上述两模块和两测试文件及本足迹均在主工作区，未提交；由整合任务继续 worker/API/数据库联调。无其他文件改动。已完成本子任务实现；真实图像服务调用、图片审美/一致性验收仍待选定服务后执行。

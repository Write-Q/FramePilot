# 后期独立工作台实现

- 日期：2026-10-23
- 关联计划：`docs/superpowers/plans/2026-10-23-postproduction-01a151.md`
- 本任务范围：`app/static/editing.html`、`editing.css`、`editing.js`、`tests/editing-ux.test.cjs`；由整合任务负责路由、分镜入口与 GitHub 阶段归档，本任务不提交他人修改。

## 已实现

- 独立 `/editing?project=&board=` 页面，沿用绿色纸感工作台；手机 390px 布局无横向溢出。
- 按后端选片顺序建立时间线；逐镜上移/下移/移除、秒级裁切、原声增益，输出横屏/竖屏/方形 24fps 预设。
- 手工字幕；WAV raw body 上传、音轨素材选择、进入时间、增益与循环；不会调用 TTS 或自动生成字幕。
- 不可变时间线保存、版本历史只读、来源状态与未保存导出门禁；409 阻止继续编辑覆盖，明确要求重新读取。
- 独立导出排队、状态刷新、结果未知标记、实际媒体地址播放器和下载；渲染成功与人工验收明确分开。
- 导出提交前把原始 payload 与幂等 key 保存到按项目/分镜隔离的 localStorage，网络响应丢失后刷新页面仍可恢复原请求。

## 验证

- 先建立浏览器测试，运行观察到页面不存在的预期失败，再实现页面。
- `node --check app/static/editing.js` 通过。
- Edge + Playwright：`node --test tests/editing-ux.test.cjs`，6/6 通过。覆盖初始原声与选片排序、裁切/字幕/预设/保存、排队、390px 布局、409、上游过期、媒体与人工验收、丢失响应后刷新幂等恢复、音轨/历史/非法区间、失败与未知状态及 HTML 注入防护、明确 409 拒绝后清除待确认请求。
- Windows sandbox 下 Edge 启动失败，已经自动审批允许在 sandbox 外运行上述本地浏览器测试。
- 使用 bundled Node，`NODE_PATH=C:/Users/blank/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules`，`FRAMEPILOT_CHROME=C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`。

## 局限与交接

- 浏览器测试使用模拟 HTTP 响应，仅证明界面流程和状态门禁，不证明真实渲染或模型质量；后端任务负责真实多镜渲染/解码与接口集成。
- 导出由独立 worker 执行，页面不自动启动 worker，也不后台轮询；刷新主动查看状态。
- 后端版本列表已经携带 content 时直接回看，否则请求 `/timeline?version=N`。
- 原始音频文件名在接口支持时显示，否则显示资产编号。
- 不含提交；待整合任务检查实际 API、路由与完整检查后一起阶段归档。

- 已检查真实 Edge 的完整手机页面截图，确认表单、按钮、版本选择器与成片档案无裁切；截图中的素材为模拟地址，不代表真实播放器解码验收。

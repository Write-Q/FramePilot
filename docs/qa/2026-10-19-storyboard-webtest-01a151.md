# 分镜网页实际测试报告

- 日期：2026-10-19
- 地址：`http://127.0.0.1:8000/storyboard`
- 环境：独立随机临时 PostgreSQL、真实 FastAPI/Edge；编剧和分镜模型为确定性替身，无付费调用，未修改业务库。
- 方式：agent-browser 逐步操作与页面观察，另外复跑 Playwright 浏览器回归。没有以模拟输出评判真实模型质量。

## 结论

本轮所测核心流程通过，未发现阻断操作的新问题。发现1项低优先级图标请求404，不影响编辑或生成；未修改产品代码。

| 实测项目 | 结果与证据 |
| --- | --- |
| 载入已确认剧本和三镜示例 | 页面显示来源V1、三镜12秒及镜头描述 |
| 编辑与保存 | 修改首镜动作，保存为V2，旧V1保留 |
| 审阅确认 | 勾选审阅后确认按钮启用；确认后显示“已确认·当前版本” |
| 历史只读 | 选择V1后，标题、镜头字段、保存/增删/移动/确认禁用；原动作保留 |
| 重新生成 | 选择三镜、9:16，通过页面产生新方案与第二条运行记录；本次是模拟模型 |
| 项目不存在 | 显示“项目不存在”，原已加载分镜保留；预期404 |
| 未确认剧本 | 载入未确认项目后生成按钮禁用、显示空态，没有模型请求 |
| 编剧/分镜跳转 | 返回编剧页载入模拟项目，再从“进入分镜工作台”进入对应项目 |
| 手机布局 | 请求390×844视口，实际截图375px；DOM观测innerWidth=390、document.scrollWidth=375，无横向溢出。工具截图与视口宽度差异未另行归因 |
| 浏览器日志 | agent-browser errors与console未返回页面JS错误；网络只有favicon和主动输入不存在项目的404 |

自动回归：`tests/test_storyboard_browser.py`、`tests/test_writer_browser.py`，**2 passed、0 skipped**，12.75秒；1项既有Starlette/AnyIO弃用警告。覆盖生成、编辑、排序、版本、确认、移动端、无效对白保护、第二镜错误刷新恢复、pending终态对账和确定性拒绝恢复。

## ISSUE-001：缺少网页图标

- 优先级：low；类别：console/资源。
- 复现：浏览器打开工作台，网络请求 `GET /favicon.ico` 返回404；后续新页面观察仍缺少图标。
- 影响：浏览器标签图标缺失，不阻断任何本轮业务操作。
- 证据：实际浏览器network记录；页面截图见下。静态资源问题，无复现视频。
- 建议：后续补统一favicon及对应路由，避免每次进入页面请求不存在资源。

## 证据与运行状态

截图在忽略目录，未提交归档：

- `.runtime/storyboard-webtest/history-readonly.png`
- `.runtime/storyboard-webtest/generated-portrait.png`
- `.runtime/storyboard-webtest/missing-project.png`
- `.runtime/storyboard-webtest/unconfirmed-blocked.png`
- `.runtime/storyboard-webtest/mobile-390.png`
- `.runtime/storyboard-webtest/desktop-final.png`

测试预览由 `.runtime/webtest_preview.py` 提供，监听本机8000，只使用本轮创建的临时测试库。模型始终模拟，即使页面添加其他配置也不会执行真实模型。服务退出时fixture负责清理它创建的随机测试库；本轮为方便用户查看保留预览服务，未承诺后台监控。结束浏览器自动化会话不等于停止预览服务器。

工具限制：agent-browser本轮鼠标click有返回成功但未发请求的情况，使用真实键盘focus/Enter完成操作；Playwright鼠标回归也通过。未将CLI自动化差异误判为产品故障。open_in_codex返回queued，因此只记录已请求打开，不声称用户当前已看到页面。

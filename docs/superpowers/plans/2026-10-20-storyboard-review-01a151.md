# 独立分镜审核 Implementation Plan

**Goal:** 已保存文字分镜可显式独立审核，保留证据和过期状态。
**Architecture:** 版本化审核提示词+受控JSON报告→单次Chat执行→证据校验→不可覆盖的运行记录→工作台展示。复用配置和存储连接，审核不改分镜。
**Tech Stack:** FastAPI/Pydantic/SQLAlchemy/PostgreSQL/httpx/原生JS/Playwright。

1. [x] 先写tests/test_storyboard_review_contracts.py验证证据和输出，再实现review_contracts.py/review_prompt.py及独立提示词清单；共享规则加载只做必要参数化。
2. [x] tests/test_storyboard_reviews.py验证HTTP行为，增加schema及冻结0007迁移、reviews.py服务；接review_provider注入和review-runs API。
3. [x] 兼容Chat执行器支持review用途，既有生成仍只允许text；配置接口返回实现状态准确。
4. [x] 扩展真实浏览器回归，实现独立JS面板并用真实浏览器验证和配置用途选择，核对旧报告/脏编辑/网络恢复。
5. [x] 跑相关测试与schema一致性，按需全量回归；只读审查、文档和本轮足迹，记录真实模型未测与业务库未迁移。

## 实施偏差与边界

契约单元先观察到缺失模块失败，再实现。服务测试写好后首次运行因未配置DB而跳过，随后因Docker崩溃连接超时，未在实现前完成HTTP缺失的红灯验证；页面也是实现后加入回归，不冒称全程严格红绿循环。Docker通过Explorer启动恢复后才完成数据库/浏览器行为验证。未迁移业务库、未真实模型调用、未提交。

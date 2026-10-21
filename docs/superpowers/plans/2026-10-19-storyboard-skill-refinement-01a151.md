# 分镜规则优化第一步 Implementation Plan

**Goal:** 完成本轮已授权的三组提示词细化，保留版本与具体来源。

**Architecture:** 一次生成调用不变，当前规则和registry组成版本化包；加载失败阻止网络调用，旧1.0.0留存核对。

**Tech Stack:** Markdown、JSON、Python/Pydantic、pytest、现有隔离PostgreSQL与浏览器回归。

1. [x] 在tests/test_storyboard_skill_bundle.py测试1.1.0元数据、完整性失败、旧哈希和语义案例边界；先确认旧代码失败。
2. [x] 保留旧三份规则及哈希，改写当前K001—K003；从固定来源按需适配，不导入画布权限、执行器或供应商品牌参数。
3. [x] registry.json保存来源定位和哈希；planning.py按清单加载/校验并产生source_locators；api.py将PlanningUnavailable映射为503。
4. [x] 新增隔离HTTP回归：篡改规则后无预约、无模型调用；新版本生成记录保存准确来源。运行单元、制作/生成及浏览器回归，最终75 passed。
5. [x] 维护9类语义验收案例和已采用来源映射；记录静态审阅结果与真实模型not_run，完成代码审查与足迹。

本轮不自动提交、推送或迁移业务库；保留现有未提交工作，后续独立审核另一步执行。

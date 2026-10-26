# 火山方舟接入实施计划

已获用户选择供应商及持续开发授权，在当前开发分支执行。

1. `tests/test_ark_adapters.py`：先验证缺失实现导致失败；覆盖单图请求、型号/尺寸/时长、提交超时、任务状态、下载认证隔离与边界。
2. `app/production/ark.py`、`contracts.py`：实现独立原生协议，显式受控视频参数。仅支持可识别的完整 Seedream / Seedance Model ID。
3. `media_service.py`、`video_runtime.py`、`video_api.py`、`store.py`、`api.py`、`assistant_actions.py`、`scripts/video_worker.py`：接入已有任务、前置校验、配置及独立 worker，保留测试注入。
4. `app/static/storyboard*.{html,js}`：提供供应商选择、视频配置和显式生成入口，保留原请求的幂等恢复，禁止未保存分镜生成。
5. `tests/test_ark_integration.py` 及浏览器用例：隔离数据库与本地真实媒体校验；执行相关回归。更新 `.env.example`、使用文档和资料库来源入口。
6. 核对差异、敏感信息、证据与局限；仅提交本任务文件，推送后核对远程 SHA。

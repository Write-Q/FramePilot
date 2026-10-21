# 型号与思考等级

## 用户决定

首批为通用兼容Chat接口与DeepSeek，日常只需要“模型型号、思考等级”两个紧凑选择器，位于输入区提交按钮附近。不添加温度/top_p/seed面板，也不在本段接远端模型发现。API地址、密钥环境变量和接口规则保留在折叠配置区。

## 实现范围

分镜生成与独立文字审核共用model-picker.js，型号来自已保存配置，显示真实model ID及配置名/版本以区分不同地址。模型型号在配置时可自由填写。切换型号同步更新档位，同型号在本标签页记住选择；待核对请求冻结型号和档位，刷新及断线恢复沿用原请求。不将设置绑定到任意后来更新的配置版本。

旧编剧仍用既有DeepSeek环境配置与LangChain执行器，本段未接入新选择器；共享编剧配置是后续独立整合，不能宣称整个产品已统一模型切换。

## 协议和边界

ModelConfig增加reasoning_protocol（none/effort/deepseek，默认none）及可选reasoning_levels。none只提供default；effort缺省提供low/medium/high，API可声明其他受控档位或缩小范围；deepseek限定none/low/high/max。声明来自用户配置，不代表远端模型已验证，未知旧配置不推断思考能力。

GenerateStoryboard与ReviewRequest增加reasoning_effort，默认default。默认明确清除保存的effort覆盖，沿用服务默认；none表示显式关闭，和default不同。非法档位在预算预约/模型请求前拒绝。

reasoning.py统一构建请求：通用旧接口维持max_tokens/temperature原默认；effort使用reasoning_effort+max_completion_tokens；DeepSeek显式关闭发送thinking.disabled、开启发送thinking.enabled及精确等级。思考协议不发送默认temperature；明确配置temperature/seed的冲突配置拒绝，不静默忽略。没有供应商错误后的自动降级或重试。

生成/审核manifest保存实际脱敏参数、转换规则版本与固定profile版本。reasoning_effort=default从幂等身份序列中省略，兼容升级前旧运行；换档位复用原幂等键仍409。不存密钥或原始思考内容。

## 存储与验证

已有JSONB配置及manifest足够，无新数据库迁移。本轮仅随机临时库测试，不写业务测试数据或调用付费模型。验收覆盖真实HTTP MockTransport请求体、旧默认、非法参数、固定版本/幂等，以及桌面/390px移动浏览器的等级联动、断线恢复和原流程回归；Mock通过不等于实际网关兼容或模型效果通过。

## 规范来源

2026-10-20核对DeepSeek官方https://api-docs.deepseek.com/guides/thinking_mode/ 和OpenAI官方https://developers.openai.com/api/reference/resources/chat。采用的是参数字段与模型差异边界，不是具体型号推荐。DeepSeek模型目录的搜索内容作为背景，直接open超时，未实现远端模型目录解析。

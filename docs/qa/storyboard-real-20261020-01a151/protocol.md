# 真实分镜效果验收方案

- 用户授权的小批文本模型调用，最多20次Chat、合计返回token超过160000则停止后续；GET/models不算生成调用。失败不自动重试；认证/限流/预算等全局错误停止。
- 模型：账户GET/models 200实际列出deepseek-flash(DeepSeek-V4.1-Flash)/deepseek-v4-pro；旧环境deepseek-chat不在目录，本轮显式选择flash，不改.env或业务profile。
- 当前planner1.1.0/reviewer1.0.0；合成输入源自9个已预定义SR案例。生成low、独立审核high；一例同输入high对照。保留一次失败，不清洗后再算首次成功率。
- 采用真实PostgreSQL随机临时库与实际HTTP API，Writer以确定性夹具只提供来源提取/确认，不将其计入真实模型质量。分镜/审核provider为真实ChatPlanner，所有请求经过业务结构/来源/证据校验；模型返回材料与软件判定分开保存。
- 逐例评估：对照fixture expected/reject逐项读取实际镜头，不把程序通过或空问题列表算作语义合格；审核评估包括已知正确的对照、植入首帧/原话错误的阳性对照。结论是本任务AI判读，未经过用户/影视专家盲审。
- 生成9例；审核SR001/2/4/5/6/7/9共7例；2条植入错误审核；1条high生成对照；预计19次，失败或预算门禁可提前停止。先SR001一次生成+一次审核canary，核对后才扩展。
- 每次记录脱敏请求体/参数、提示词manifest、最终JSON、服务status/usage、耗时。记录服务返回的model/system_fingerprint（若有）；不保存Authorization或reasoning_content，不将无快照名别名宣称固定底层权重。
- 仅本任务新建测试库/合成案例可修改；业务库不改。结果先逐次落盘，再结束或删除本任务精确测试库，记录清理状态。没有后台监控或自动收费重试。

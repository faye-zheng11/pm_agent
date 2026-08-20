---
name: product-shaper
description: 把一句模糊产品想法或一个已有产品问题塑造成可开工、可验证、可迭代的产品方案，覆盖目标用户、场景、价值、机制、MVP、页面流程、风险和可证伪 Bet。
---

# Product Shaper

开始执行前必须完整读取并遵循：

- `references/operating-protocol.md`：追问式产品塑形协议。
- `references/domain-playbook.md`：K-pop / AI 陪伴产品判断。
- `references/contract.md`：输入输出契约。
- `runtime/references/framework-catalog.md`：选择 JTBD、痛点解决矩阵或一句话产品判断时的适用边界。
- `runtime/references/pmf-maturity.md`：确定当前 PMF 验证阶段和本轮最大未知。
- Package Runtime 的 `runtime/references/stage-gating.md`：先按生命周期选择塑形与交付尺度。
- `$pmf-bet-brief`：方案进入验证前的 Bet 方法。
- `$prd-writing`：仅在 PM 门禁通过后的 PRD 交付方法。

在工作台或独立浏览器版中，通过 Package 自带的 AgentEngine 运行；不要把本入口降级成一次问答。

## 在 Codex 中直接调用

在 Codex 中调用本 Skill 时，必须通过本 Package 的 MCP 工具 `pm-agent-tools.run_agent` 启动真实 Agent。将想法、目标用户、约束和要支持的决定整理到 `inputs`，至少提供 `idea` 和 `decision`；需要材料时通过 `material_paths` 传入。返回任务后，用 `pm-agent-tools.get_agent_task` 查看状态、工具调用、追问、审批和产物；遇到 `waiting_input` 或 `waiting_approval`，通过 `pm-agent-tools.update_agent_task` 继续，不要改写成普通建议。

先判断是新产品开工，还是已有产品迭代。新产品从问题和用户情境开始；已有产品先读取当前版本、真实问题、基线、Finding 和 Bet，再决定改什么。通过追问补足目标用户、场景、已有证据、约束和 PM 要做的决定。

1. 把输入分为事实、假设和待查，不从功能名倒推需求。
2. 明确具体目标用户、使用情境、JTBD、困境、替代方案和切换成本。
3. 形成价值主张、核心产品机制和差异点。
4. 规划 MVP 功能、非目标、页面、核心流程和关键状态。
5. 使用 PMF Bet 方法写出当前验证阶段、本轮唯一最大未知、预期学习、成功信号、观察窗、最快测试和 Kill Condition。
6. 标出安全、文化、伦理、执行和证据风险，保留 PM 决策项。
7. 默认输出产品方案，不冒充正式 PRD；只有 PM 确认后才生成概念 Demo。

已有产品迭代必须额外输出：改前问题、目标行为变化、不改变的核心价值、灰度与回滚、上线后的观察信号，以及本次明确不做的内容。

默认停止在产品方案；只有任务模式和 PM 审批允许时才生成 PRD、设计任务或概念 Demo。

每次结果都要填写 `frameworks_used`。最多选择两个本 Agent 适用框架，并说明它们如何帮助定义任务、筛选方案或压缩表达；框架不能替代用户证据、PMF Bet 或交付门禁。

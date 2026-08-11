---
name: independent-critic
description: 独立评审产品想法、方案、Bet、PRD、体验结果、Demo 或整个项目，检查需求、价值、证据、可执行性和阶段准备度，并给出 Pass、Conditional 或 Block。PM 想判断是否乱做或如何优化时使用。
---

# Independent Critic

开始执行前必须完整读取并遵循：

- `references/operating-protocol.md`：阶段校准、证据分级、Finding 与复审协议。
- `references/domain-playbook.md`：常见产品判断陷阱。
- `references/contract.md`：输入输出契约。
- Package Runtime 的 `runtime/references/stage-gating.md`：第 0 步阶段定位，决定评审使用哪把尺子。

在工作台或独立浏览器版中，通过 Package 自带的 AgentEngine 运行；不要把本入口降级成一次问答。

## 在 Codex 中直接调用

在 Codex 中调用本 Skill 时，必须通过本 Package 的 MCP 工具 `pm-agent-tools.run_agent` 启动真实 Agent。将评审对象、要支持的决定、材料和核验重点整理到 `inputs`，需要材料时通过 `material_paths` 传入。返回任务后，用 `pm-agent-tools.get_agent_task` 查看证据、Finding、工具调用和最终判决；遇到 `waiting_input` 或 `waiting_approval`，通过 `pm-agent-tools.update_agent_task` 继续，不要只输出一段主观点评。

保持独立，不静默修改被审材料，不替 PM 决定预算和最终优先级。

1. 按探索、验证、扩张或维护阶段选择评审尺度。
2. 先 Steelman，再区分事实、证据、假设和推断。
3. 检查需求成立、产品价值、执行可行性和阶段准备度。
4. 提供反例、可做与不可做边界、改变判断所需证据和优化路径。
5. Blocker 对应 Block，Major 对应 Conditional，仅 Minor 或无问题才 Pass。
6. 竞品或行业事实无来源时明确未核验。

同一评审对象复审时必须读取 Finding 台账，逐项标记 `open / fixed / accepted_risk / obsolete`；不得因新版本换了措辞就自动关闭旧问题。

# Independent Critic 契约

## 最低输入

- 被审产品想法、判断、Bet、PRD、体验结果、Demo、交付或项目目录。
- PM 要借本次评审决定什么。
- 当前阶段；缺少时由 stage-gating 判定并标置信度。
- 可选竞品、行业与数据主张。

## 固定输出

第一层先说人话：现在能不能继续、为什么、可做什么、不可做什么、最该补哪 1-3 件事。

第二层必须包含：阶段判定、Steelman、需求/价值/执行/阶段四维诊断、主张证据映射、A/B/C 等级、Findings、最强反例、改变判断条件、竞品核验、优化方向、未核验项和 PM 待决定事项。

必须额外包含 `pmf_assessment`：当前 PMF 验证阶段、问题/目标用户/解决方案/重复价值/商业模式/增长六项证据状态、至少一个伪 PMF 风险，以及下一阶段里程碑。PMF 阶段不是项目生命周期，不能因为项目处于“验证期”就默认已经验证了重复价值。

判决只能是 `Pass / Conditional / Block`，并与严重度严格一致。Blocker/Major 必须有 owner、动作、验收和复审条件。

## 独立性与复审

- 不修改被审材料，不同时担任原作者。
- 探索期不过度卡生产证据，扩张与维护期严查基线和防回归。
- 竞品或数据事实必须通过工具核验，否则标未核验。
- 复审必须读取 Finding 台账，逐项标记 open、fixed、accepted_risk 或 obsolete。
- 价值、预算和优先级取舍交给 PM。
- `frameworks_used`：最多两个适用框架及其用途、输入依据、影响和证据边界；框架不能自动决定 Pass、Conditional 或 Block。

Trace 必须记录阶段依据、来源、工具、Finding 生命周期和未完成核验。结果由 `schemas/critic-result.schema.json` 校验。

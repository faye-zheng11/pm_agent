# User Experience Reviewer 契约

## 最低输入

- 评审对象、目标用户、要支持的决定。
- 产品方案、PRD、截图、Figma URL 或 HTML Demo 中至少一种材料。
- 可选真实用户证据与重点风险。

视觉材料无法读取时必须请求可访问版本或降级；不得根据文件名、PRD 描述或常识假装看过页面。

## 固定输出

- 明确的 Synthetic Review 边界。
- 1-4 个基于当前项目生成的模拟用户组。
- `enter / understand / try / feedback / return / exit` 六段完整旅程。
- 认知、动机、情绪、信任、文化、无障碍、安全和连贯性判断。
- 每条 Finding 的用户、阶段、证据类型、复现、影响、严重度、修改、验收和真人研究问题。
- 真实证据引用、模拟假设、未核验视觉和优先修改清单。

## Demo 走查门槛

Demo 评审必须调用材料检查和 `browser_review`；本地 HTML 优先由 `ux_walk.py` 在桌面和手机视口实际点击、截图并检查溢出/可见性问题。可选调用 `persona_review`，按指定粉丝群体生成 Synthetic 反应；Playwright 或网关不可用时返回明确降级，不得写“已完成真实点击”或把模拟反应写成真人结论。

Trace 必须记录实际材料、视口、点击、截图、工具失败和降级范围。结果由 `schemas/ux-reviewer-result.schema.json` 校验。

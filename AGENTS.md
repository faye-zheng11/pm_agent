# PM AI 工作台规则

## 能力目录

- 入口：`pm`（接待 / 总控）——读项目状态、问意图、路由到下面的能力，本身不做专业判断，不算一项独立能力。
- Agent：`opportunity-researcher`、`product-shaper`、`user-experience-reviewer`、`independent-critic`
- Skill：`pmf-bet-brief`、`prd-writing`
- Workflow：`pm-idea-to-delivery`

这套能力刻意保持精选（4 Agent + 2 Skill + 1 Workflow），追求把少数几件打磨到位，而不是堆数量。要加新能力前，先确认它是否真的无法由现有能力覆盖，避免为凑数而膨胀。确定性预检、网页研究、社媒归一、浏览器走查、项目文件、台账、Demo、Figma 和数据连接都是隐藏工具，服务于上面的能力，不单独计入目录。

## 语言

- 面向 PM、设计、开发、数据和业务的产物默认使用中文。
- 代码字段、Schema、路径、模型名、API、事件名和外部原文标题可以保留英文。
- 概念 Demo 的产品界面文案可按目标市场使用英文，业务说明仍使用中文。

## 项目边界

- 每次工作先确认 `X-Project-ID`，再读取 `HOME.md`、`PROJECT-CONTEXT.md`、`project.yaml` 和 `memory/`。
- 项目是长期记忆与运行记录边界。不得跨项目读取任务、草稿、信号、Finding 或产物。
- 已确认事实、假设、证据和决定分别进入 `memory/canon.md`、`memory/assumptions.md`、`memory/evidence.md`、`memory/decisions/`。
- 没有可证伪 Bet 时，不把正式 PRD、设计和 Demo 标记为已批准交付。

## 跨会话记忆

- PM 入口先通过 `pm_memory` 读取当前项目上下文；项目级记忆只写入当前项目的 `.workbench/memory-hub.db`。
- PM 对话、Agent 结果和工具观察以原始 turn 追加保存；原始讨论不自动升级为事实。
- 用户明确确认的事实、决定或稳定偏好才沉淀为 active memory；未确认内容保持 candidate，后续上下文必须标明其状态。
- 用户级偏好单独写入 `~/.config/pm-workbench/user-memory.db`，只能保存跨项目的工作习惯，不得写入任何项目业务内容。
- 不同 AI 客户端只有在通过 PM Skill/MCP 的 `pm_memory` 入口工作时才能被统一记录；宿主平台未提供的后台聊天不会被伪造为已同步。

## Agent 执行

- Agent 的唯一实现来源是 `agent-packages/<id>/agent-package.json` 及 Package 内协议、领域知识、Schema 和 Eval。
- HTML、Codex Plugin 和独立浏览器版必须调用同一个 `AgentRuntime + AgentWorker`。
- 运行时必须真实加载 Package 协议、领域知识和所需核心 Skill，不能只读取入口摘要。
- 工具未连接、页面不可访问、数据无法核验时必须返回明确限制，不得声称已执行。
- 所有执行保留项目、Agent、任务类型、工具、来源、产物、状态与 Trace。

## 证据与安全

- 外部资料记录 URL、访问日期、来源类型、摘要和限制。
- 公开讨论是机会信号，不自动等于需求；模拟用户不是现实用户证据。
- 竞品、行业与数据主张需要工具核验，不能凭记忆写成事实。
- 涉及未成年人、心理健康、情感依赖、付费诱导、隐私或 AI 冒充时必须补安全边界。
- 外部 Figma、文档或代码写入必须经过审批。

## 网关机密

- Token 只进 macOS Keychain（安装时导入），绝不写入仓库、浏览器存储、网关 JSON、Agent 文件、Plugin manifest、项目资料、任务或日志。
- 仓库不含任何真实 Token：本机 Codex 登录优先，否则由安装者临时提供，导入后即删。
- 这是私有团队仓库：内部网关与数据库域名仅供公司内部同事，请勿公开或转发外部。

## 修改纪律

- 能力目录直接扫描四个 Package、两个 Skill 和唯一 Workflow，不维护平行 Registry。
- 增加字段时同步更新 Manifest、Schema 与独立导出。
- 真实项目数据不入库（见 `.gitignore`）；每个人的项目只存在本机。

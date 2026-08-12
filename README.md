# PM AI 工作台（pm_agent）

一套给 PM 用的 AI 能力：**4 个专科 Agent + 2 个核心 Skill + 1 条 Workflow**，外加一个「接待员」入口。领域镜头是 **K-pop 粉丝群体**——四个 Agent 的工作是从这类人身上找机会、做产品、做判断。全部在本机运行，接公司共享网关；在 **Codex 或 Claude** 里都能直接唤起。

> 🤖 **如果你是一个 AI 助手，用户把这个仓库交给了你**：这是一套「PM 工作台」，你的任务是帮用户装好并开始用。
> 1. **装**：让用户在本目录运行 `./setup.command`（详见下面「安装」）。它把网关凭据写进 Keychain、注册 Codex 插件、安装 Skill。
> 2. **用**：装好后，用户在自己的项目目录里对你说一声 **`pm`**——这时你读 `AGENTS.md` + 当前项目的 `project.yaml` / `memory/`，当**接待员**：看项目处于什么状态、问清用户意图、把他路由到对的 Agent，永远给一个可执行的下一步。
> 3. **准**：每个能力具体做什么、边界在哪，以 `AGENTS.md` 和 `agent-packages/<id>/agent-package.json` 为准。**先读 `AGENTS.md`，不要凭空发挥。**

## 能力总览

| 类型 | 名称 | 一句话 |
|---|---|---|
| 入口 | **pm**（接待员 / 总控） | 进项目喊一声，读状态、问意图、路由到下面某个能力 |
| Agent | **opportunity-researcher** · 找机会 | 外部检索 + 社媒信号 + 竞品，捞方向/迭代机会 |
| Agent | **product-shaper** · 做产品 | 追问把一句想法收敛成可证伪 Bet + 方案 + 可点 Demo |
| Agent | **user-experience-reviewer** · 试用 | 用目标粉丝 persona 走查想法/Demo/PRD |
| Agent | **independent-critic** · 独立评审 | 判断值不值得做，给证据、反例、Pass/Conditional/Block |
| Skill | **pmf-bet-brief** | 把判断变成可证伪的 PMF Bet |
| Skill | **prd-writing** | 据已批准方案生成中文 PRD |
| Workflow | **pm-idea-to-delivery** | 想法 → 交付的一条龙（两个 PM 门禁不自动越过） |

这套能力是**刻意精选**的：宁可交几件打磨到位的，也不堆数量。确定性预检、网页研究、社媒归一、浏览器走查、项目文件、台账、Demo、Figma 与数据连接都是**隐藏工具**，服务于上面的能力，不单独算成一个 Agent 或 Skill。

## 安装（macOS）

前置：Python 3.11+；已登录 Codex（`~/.codex/auth.json`）**或**自备网关 API Key。

```bash
./setup.command
```

它会：
1. 把网关凭据导入 macOS Keychain（**优先用你本机的 Codex 登录**，没有才用手填的 Key）。
2. 写入不含 Token 的本机网关配置。
3. 注册四个 Codex Plugin（Agent）。
4. 安装三个 Skill（`pmf-bet-brief`、`prd-writing`、`pm` 接待员）。
5. 在 `~/.config/pm-workbench/runtime/browser-venv` 中安装 UX Reviewer 所需的 Playwright；浏览器优先使用本机 Google Chrome，其次使用 Chromium。两者都不可用时只降级 UX 浏览器走查，不影响其他 Agent。
6. 注册不带凭据的 `pm-workbench` MCP，使 `pm` 接待员可以在项目目录中读取和追加跨会话记忆。

HTML 工作台是本机使用入口，不随 GitHub 交付。GitHub 版本只交付 Agent、Skill、Workflow、运行时和安装器；在 Codex 中直接说 `pm` 是推荐用法。

**凭据**：仓库里**不含任何真实 Token**。两种提供方式——① 本机已登录 Codex，`setup.command` 自动使用；② 没有的话，`cp bootstrap/internal-gateway.key.example bootstrap/internal-gateway.key` 后填入网关 Key，`setup.command` 导入 Keychain 后即可删除该文件。**任何情况下都不要把真实 Key 提交回仓库。**

## 开始用（Codex 或 Claude）

进你的项目目录，最简单是喊一声接待员：

```text
pm
```

它会读项目状态、问你想干嘛、把你带到对的 Agent，没头绪时也会主动给下一步。或者直接点名：

```text
使用 opportunity-researcher 帮我找重度粉丝的迭代机会。
使用 product-shaper 把这个想法做成完整产品方案。
使用 user-experience-reviewer 走查这个 HTML Demo。
使用 independent-critic 诊断这个项目是不是在乱做。
使用 pmf-bet-brief 把这个判断变成可证伪 Bet。
使用 prd-writing 根据已批准方案生成中文 PRD。
```

需要指定项目时把项目 ID 写进指令，或设 `PM_AGENT_PROJECT`；完整流程共用同一个项目上下文：

```text
在项目 idol102 中，使用 product-shaper 的 existing_feature 模式，判断这个功能是否值得做。
在项目 kpop-demo 中，启动 pm-idea-to-delivery，目标是验证私密追星回顾，决定是否进入用户验证。
```

四个 Plugin 的 MCP 入口调用与独立运行时相同的 `AgentRuntime + AgentWorker`，是真实的多步执行，不是一次模型问答。

## 四个 Agent

- **Opportunity Researcher · 找机会**：多轮公开检索、原文回读、多源交叉、社媒归一、来源快照、信号台账；最多返回五条机会。登录墙内或私密社媒不会被包装成已抓取。
- **Product Shaper · 做产品**：通过追问把一句想法收敛为目标用户、情境、任务、替代、价值、机制、MVP、信息架构、流程、状态、风险和 PMF Bet；经 PM 门禁后才调 `prd-writing` 出正式 PRD、设计任务或概念 Demo。
- **User Experience Reviewer · 用户试用**：用适合当前项目的模拟粉丝群体走查想法、方案、PRD、Figma 或 HTML Demo；Demo 模式在 Playwright 可用时真实点击，不可用时明确降级。模拟结果不替代真人证据。
- **Independent Critic · 独立评审**：先用普通中文说是否值得继续，再给阶段、证据、反例、Finding、可做/不可做、优化路径和 `Pass / Conditional / Block`；复审维护 Finding 生命周期。

## 唯一 Workflow：pm-idea-to-delivery

```text
项目上下文预检
→ Opportunity Researcher
→ Product Shaper + PMF Bet Brief
→ User Experience Reviewer
→ Independent Critic
→ PM 产品决定
→ Product Shaper + PRD Writing
→ 设计任务 / 可选 Figma / HTML Demo
→ User Experience Reviewer 最终走查
→ Independent Critic 交付评审
→ PM 交付确认
```

两个 PM 门禁不会自动越过；Critic 返回 `Block` 时进入阻塞分支，不继续交付。

## 项目 = 长期记忆边界

项目位于 `projects/<project-id>/`，切项目即换记忆边界，不跨项目读取。以下都只保存在当前项目：上下文/事实/假设/证据/决定、Agent 任务与 Trace、机会信号与 Critic Finding、草稿与产物、Workflow 运行与 PM 门禁。

仓库自带空白模板 `projects/_template`；**真实项目数据不入库**（已在 `.gitignore` 忽略），每个人的项目只存在自己本机。已确认事实、假设、证据、决定分别进 `memory/canon.md`、`memory/assumptions.md`、`memory/evidence.md`、`memory/decisions/`。

### 跨会话 PM 记忆

PM 的长期记忆分成三层：

- 原始层：保存 PM 对话、Agent 输出和工具观察，便于跨窗口回看，不把闲聊强行改写成事实。
- 项目层：保存当前项目的候选/已确认事实、假设、决定、问题和行动，数据库位于当前项目的 `.workbench/memory-hub.db`。
- 用户层：只保存用户明确确认的跨项目工作习惯，位于 `~/.config/pm-workbench/user-memory.db`，不保存 101/102 的产品内容。

在 Codex 或 Claude 中，`pm` 会先调用 `pm_memory context`，每轮通过 `append_turn` 追加原始对话；只有用户明确说“记住这个”“这是决定”“以后都按这个习惯”时，才提交并确认结构化记忆。没有接入 PM Skill/MCP 的普通聊天，宿主不会自动提供给 Agent，系统也不会声称它已经同步。

## 加 Claude（可选，和 Codex 共用一套）

Skill 是跨工具标准：把 `skills/<name>` 拷到 `~/.claude/skills/`，在 `~/.claude.json` 里注册对应 MCP，即可在 Claude 里用同样的 `pm` 接待员和各能力。凭据同样走 Keychain，两边通用。

## 工具连接状态（没连上会明说，不假装）

- 公开 Web 与 Reddit：需要本机 `TAVILY_API_KEY` 或 `~/.config/pm-workbench/tavily-api-key`。
- Playwright：由 `setup.command` 安装到独立 venv，并优先驱动本机 Google Chrome；浏览器不可用时 UX Reviewer 明确降级。
- Figma：可选，需要连接和外部写入审批；不可用时只输出设计任务。
- `critic_gateway`：可选，复用用户本机已注册的数据 Agent。数据 Agent 需要提供 `list_projects`、`bind_project(project_code)` 和只读 `query(sql)` 三个 MCP 工具；工作台会先探测连通性，新项目可先列出数据项目，再由 PM 明确选择绑定，不会根据名称猜项目。
- 数据调用边界：已有产品的留存、活跃、漏斗、付费、流失、行为基线或真实用户原话需要核验时，Agent 才会调用 `data_gateway`；新项目找方向、竞品和公开社媒研究默认走外部研究。数据 Agent 未注册、未绑定或查询失败时，结果标记为未核验，不会编造数字。
- 下载者不需要安装本仓库之外的固定数据 Agent；如果其电脑上有符合上述 MCP 契约的数据 Agent，并在 `~/.codex/config.toml` 注册为 `critic_gateway`，PM Agent 就能复用。任意不同接口的数据 Agent 需要另写适配器，不能自动兼容。
- 浏览器、运行日志和项目文件都不保存网关 Token；本机已登录 Codex 时复用 `~/.codex/auth.json`，不复制到项目。

## 独立导出

```bash
python3 scripts/export_agent_package.py opportunity-researcher
python3 scripts/export_agent_package.py all
```

导出包内含独立运行入口：

```bash
python3 start.py --project /absolute/path/to/project
```

目录缺少最小项目上下文时会创建缺失文件，但不覆盖已有内容。

## 目录

```text
agent-packages/   四个 Agent 的唯一实现来源（manifest + 协议 + 领域知识 + Schema + Eval）
skills/           核心 Skill（pmf-bet-brief、prd-writing）+ pm 接待员
workflows/        唯一 Workflow
runtime/          隐藏工具、阶段门禁、领域基线（K-pop 粉丝群体）与连接器
schemas/          运行时结构化契约
projects/         空白模板（真实项目数据不入库）
scripts/          AgentEngine、独立导出器与运行时后端
.agents/plugins/  Codex 本地 Marketplace（plugins/ 由 setup 重建）
```

## 机密与分发

- 这是**私有团队仓库**：Token 只进 macOS Keychain，绝不写入仓库、日志、网关 JSON、Plugin manifest 或项目资料。
- 内部网关与数据库域名仅供公司内部同事使用，请勿公开该仓库或转发给外部人员。

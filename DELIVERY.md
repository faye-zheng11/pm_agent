# 交付说明

## 给同事

1. 将整个目录放到本机内部工作目录。
2. 双击 `setup.command` 完成 Keychain、Plugin、Skill、Marketplace 和 Playwright 安装；如果浏览器不可用，脚本会明确提示，其他 Agent 仍可用。
3. HTML 工作台只在内部本机保留，不随 GitHub 交付；推荐在 Codex 项目对话中直接说 `pm`。
4. 在 Codex 中进入自己的项目目录后说 `pm`，或直接点名需要的 Agent/Skill。

如果同事已经有资料，点击网页右上角 `+` → `导入已有资料`，可一次选择文件夹或文件，并登记 Figma / 飞书链接。导入后首页会显示资料清单、当前阶段、最近任务和下一步建议；外部链接需要对应连接器或授权才能读取。

## 能得到什么

- 四个可单独运行、可追问、可暂停恢复、可审批、可追溯的 Agent。
- 两个可在 Codex 独立调用、也被 Product Shaper 和 Workflow 使用的核心 Skill。
- 一条有两次 PM 门禁、Critic 真实分流的从想法到交付 Workflow。
- HTML、Codex Plugin 和独立导出三种入口，共享同一 AgentEngine。

## 不包含什么

- 不包含历史真实项目、报告、数据、会话和运行记录。
- 不保证读取登录后社媒；Researcher 只处理公开来源或用户提供的导出。
- 不把模拟用户评审当真人研究。
- Figma、公开研究、浏览器和数据连接未配置时会明确降级。

## 机密边界

安装器优先使用同事本机已登录 Codex 的凭据，并导入 macOS Keychain；没有本机凭据时才使用交付包内的内部安装凭据。具备本机访问权限的人员理论上仍可提取 Token，只能在公司内部可信范围传递。

## 恢复原工作台

交付仓库不包含历史资料。重构前完整归档位于仓库外：

`/Users/apple/develop/code/workbench-archive-20260811-093426.tar.gz`

SHA-256：`384ca60750bcbec1879816a99719bcc5b5c33d505bece51448920c830f1b43a0`

本次移出的旧目录还暂存在：

`/Users/apple/.Trash/pm-workbench-pruned-20260811-101500`

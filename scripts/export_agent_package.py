#!/usr/bin/env python3
"""导出与工作台使用同一 AgentEngine 的独立 Agent Package。"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "agent-packages"
PUBLIC_IDS = {"opportunity-researcher", "product-shaper", "user-experience-reviewer", "independent-critic"}
EXPORT_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def portable_path(value: str, package_id: str) -> str:
    prefix = f"agent-packages/{package_id}/"
    return value[len(prefix):] if value.startswith(prefix) else value


def export_package(package_id: str, output_root: Path) -> tuple[Path, Path]:
    if package_id not in PUBLIC_IDS:
        raise ValueError(f"未知公开 Agent Package: {package_id}")
    source = PACKAGE_ROOT / package_id
    target = output_root.resolve() / package_id
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=EXPORT_IGNORE)

    shared = PACKAGE_ROOT / "_shared"
    (target / "assets").mkdir(exist_ok=True)
    (target / "runtime").mkdir(exist_ok=True)
    shutil.copy2(shared / "standalone_server.py", target / "scripts" / "standalone_server.py")
    shutil.copy2(ROOT / "scripts" / "gateway_client.py", target / "scripts" / "gateway_client.py")
    shutil.copy2(shared / "package_mcp_runtime.py", target / "scripts" / "package_mcp_runtime.py")
    shutil.copy2(shared / "standalone.html", target / "assets" / "standalone.html")
    shutil.copy2(ROOT / "scripts" / "agent_runtime.py", target / "runtime" / "agent_runtime.py")
    shutil.copy2(ROOT / "runtime" / "tools.json", target / "runtime" / "tools.json")
    shutil.copy2(ROOT / "runtime" / "memory_hub.py", target / "runtime" / "memory_hub.py")
    shutil.copytree(ROOT / "runtime" / "references", target / "runtime" / "references", dirs_exist_ok=True, ignore=EXPORT_IGNORE)
    shutil.copytree(ROOT / "runtime" / "connectors", target / "runtime" / "connectors", dirs_exist_ok=True, ignore=EXPORT_IGNORE)
    shutil.copytree(ROOT / "schemas", target / "schemas", dirs_exist_ok=True, ignore=EXPORT_IGNORE)
    shutil.copytree(ROOT / "skills" / "pmf-bet-brief", target / "skills" / "pmf-bet-brief", dirs_exist_ok=True, ignore=EXPORT_IGNORE)
    shutil.copytree(ROOT / "skills" / "prd-writing", target / "skills" / "prd-writing", dirs_exist_ok=True, ignore=EXPORT_IGNORE)

    manifest_path = target / "agent-package.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("protocols", "domain_knowledge"):
        manifest[key] = [portable_path(item, package_id) for item in manifest[key]]
    manifest["runtime"]["skills"] = [portable_path(item, package_id) for item in manifest["runtime"]["skills"]]
    manifest["runtime"]["knowledge_assets"] = [portable_path(item, package_id) for item in manifest["runtime"]["knowledge_assets"]]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    readme = f"""# {manifest['name']} · 独立 Agent

这个包与 PM 工作台使用同一份 `AgentRuntime + AgentWorker`，支持工具循环、结构化追问、暂停恢复、审批、项目记忆和 Trace。

```bash
python3 start.py --project /absolute/path/to/your-project
```

也可以把本目录作为 Codex Plugin 安装。首次运行会在指定项目缺少最小上下文时创建 `HOME.md`、`PROJECT-CONTEXT.md`、`project.yaml` 和 `memory/`，不会覆盖已有内容。

跨会话记忆按项目保存在项目目录的 `.workbench/memory-hub.db`；用户级偏好保存在 `~/.config/pm-workbench/user-memory.db`。通过 MCP 的 `pm_memory` 读取当前项目上下文、追加原始对话，或在用户确认后沉淀事实/决定。不同项目不会共享项目内容。

网关 Token 只从 macOS Keychain service `pm-workbench-ai-gateway` / account `default` 或 `PM_WORKBENCH_API_KEY` 读取。
"""
    (target / "PACKAGE-README.md").write_text(readme, encoding="utf-8")
    for path in (target / "start.py", target / "scripts" / "mcp_server.py", target / "scripts" / "standalone_server.py", target / "scripts" / "package_mcp_runtime.py"):
        path.chmod(path.stat().st_mode | 0o111)
    archive = output_root.resolve() / f"{package_id}-{manifest['version']}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                bundle.write(path, Path(package_id) / path.relative_to(target))
    return target, archive


def main() -> None:
    parser = argparse.ArgumentParser(description="导出独立 PM Agent Package")
    parser.add_argument("package", choices=sorted(PUBLIC_IDS) + ["all"])
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "agents")
    args = parser.parse_args()
    package_ids = sorted(PUBLIC_IDS) if args.package == "all" else [args.package]
    args.output.mkdir(parents=True, exist_ok=True)
    packages = []
    for package_id in package_ids:
        target, archive = export_package(package_id, args.output)
        packages.append({"id": package_id, "path": str(target), "zip": str(archive)})
    print(json.dumps({"ok": True, "packages": packages}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""PM 工作台根 MCP 入口：在 Codex 中运行四个 Agent 或唯一 Workflow。"""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cockpit_server as cockpit


EXTERNAL_PROJECT_ALIASES = {
    Path("/Users/apple/develop/code/idol 101").resolve(): "idol101",
    Path("/Users/apple/develop/code/idol 109").resolve(): "idol109",
}
PROJECT_ID_ALIASES = {"idol-101": "idol101", "idol-109": "idol109"}


def resolve_project(arguments: dict[str, Any]) -> str:
    candidate = str(arguments.get("project_id") or arguments.get("project") or os.environ.get("PM_AGENT_PROJECT") or "").strip()
    if not candidate:
        raise ValueError("请指定 project_id，例如 idol102；也可以设置 PM_AGENT_PROJECT")
    path = Path(candidate).expanduser()
    if path.is_dir():
        resolved_path = path.resolve()
        aliased = EXTERNAL_PROJECT_ALIASES.get(resolved_path)
        if aliased:
            # Codex 在外部产品仓库工作时，仍写入工作台的 canonical Memory Hub，
            # 因此网页和 Codex 不会各自维护一套“看起来相同”的记忆。
            os.environ.pop("PM_AGENT_PROJECT_DIR", None)
            cockpit._runtime = None
            cockpit.runtime().projects.resolve(aliased)
            return aliased
    if path.is_dir() and (path / "manifest.yaml").is_file():
        os.environ["PM_AGENT_PROJECT_DIR"] = str(path.resolve())
        cockpit._runtime = None
        projects = cockpit.runtime().projects.discover()
        for project_id, project in projects.items():
            if project["path"].resolve() == path.resolve():
                return project_id
        raise ValueError(f"目录不是有效项目: {path}")
    canonical = PROJECT_ID_ALIASES.get(candidate, candidate)
    cockpit.runtime().projects.resolve(canonical)
    return canonical


def run_agent(arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = resolve_project(arguments)
    package_id = str(arguments.get("agent_id") or "").strip()
    package = cockpit.runtime().registry.packages.get(package_id)
    if not package:
        raise ValueError("未知 Agent；可用值：opportunity-researcher、product-shaper、user-experience-reviewer、independent-critic")
    mode_id = str(arguments.get("mode") or package["modes"][0]["id"])
    mode = next((item for item in package["modes"] if item["id"] == mode_id), None)
    if not mode:
        raise ValueError(f"Agent 模式无效: {mode_id}")
    inputs = arguments.get("inputs") if isinstance(arguments.get("inputs"), dict) else {}
    goal = str(arguments.get("goal") or "\n".join(f"{key}: {value}" for key, value in inputs.items() if str(value).strip())).strip()
    decision = str(arguments.get("decision_to_support") or inputs.get("decision") or "判断当前材料是否足以支持下一步，并给出明确行动").strip()
    if not goal:
        raise ValueError("请提供 goal 或 inputs")
    if mode.get("approval_required") and arguments.get("pm_confirmed") is not True:
        raise ValueError("该模式需要 pm_confirmed=true")
    runtime = cockpit.runtime()
    runtime_agent_id = package["runtime_agent_id"]
    active_tools = cockpit.available_tools()
    allowed = [tool for tool in runtime.registry.agents[runtime_agent_id]["allowed_tools"] if tool in active_tools]
    material_paths = normalize_material_paths(project_id, arguments.get("material_paths") or arguments.get("source_artifacts") or [])
    task, _ = runtime.create_task(
        project_id=project_id,
        agent_id=runtime_agent_id,
        task_type=mode["task_type"],
        goal=goal,
        decision_to_support=decision,
        source_artifacts=material_paths,
        allowed_tools=allowed,
        authority_level="draft_write",
        idempotency_key=str(arguments.get("idempotency_key") or ""),
        memory_source=str(arguments.get("source") or "codex"),
        memory_session_id=str(arguments.get("session_id") or ""),
    )
    worker = cockpit.AgentWorker(runtime, cockpit.gateway_model, cockpit.ToolExecutor(runtime, cockpit.handlers()))
    worker.run_with_retries(task["id"], "codex-workbench-worker")
    return cockpit.task_details(task["id"])


def normalize_material_paths(project_id: str, values: Any) -> list[str]:
    """Convert Codex file paths into project-relative, authorized material paths."""
    if not isinstance(values, list):
        raise ValueError("material_paths 必须是字符串数组")
    project = cockpit.runtime().projects.resolve(project_id)
    project_path = project["path"].resolve()
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("material_paths 只能包含非空字符串")
        item = value.strip()
        if item.startswith(("http://", "https://")):
            normalized.append(item)
            continue
        candidate = Path(item).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve()
            try:
                relative = resolved.relative_to(project_path).as_posix()
            except ValueError:
                if not resolved.is_file():
                    raise ValueError(f"外部材料不存在或不是文件: {item}")
                # Explicitly supplied external files become a project-owned upload.
                # This preserves project isolation while making Codex absolute paths usable.
                digest = hashlib.sha256(
                    f"{resolved}:{resolved.stat().st_size}:{resolved.stat().st_mtime_ns}".encode("utf-8")
                ).hexdigest()[:12]
                upload_dir = project_path / ".workbench" / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                target = upload_dir / f"codex-{digest}-{resolved.name}"
                if not target.exists():
                    shutil.copy2(resolved, target)
                relative = target.relative_to(project_path).as_posix()
            normalized.append(relative)
            continue
        prefix = f"projects/{project_path.name}/"
        if item.startswith(prefix):
            item = item[len(prefix):]
        normalized.append(item)
    return list(dict.fromkeys(normalized))


def run_workflow(arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = resolve_project(arguments)
    goal = str(arguments.get("goal") or "").strip()
    decision = str(arguments.get("decision_to_support") or arguments.get("decision") or "").strip()
    if not goal or not decision:
        raise ValueError("Workflow 需要 goal 和 decision_to_support")
    scheduler = cockpit.WorkflowScheduler(cockpit.runtime(), cockpit.available_tools())
    run = scheduler.start(project_id, cockpit.CORE_WORKFLOW, goal, decision)
    cockpit.run_workflow(run["id"])
    return scheduler.get(run["id"])


def get_agent_task(arguments: dict[str, Any]) -> dict[str, Any]:
    return cockpit.task_details(str(arguments.get("task_id") or ""))


def update_agent_task(arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = str(arguments.get("task_id") or "")
    action = str(arguments.get("action") or "")
    runtime = cockpit.runtime()
    if action == "provide_input":
        runtime.store.provide_input(str(arguments.get("input_id") or ""), arguments.get("responses") or {}, "pm")
    elif action == "decide_approval":
        runtime.store.decide_approval(str(arguments.get("approval_id") or ""), bool(arguments.get("approved")), "pm", str(arguments.get("note") or ""))
    else:
        raise ValueError("action 只能是 provide_input 或 decide_approval")
    task = runtime.store.get(task_id)
    if task["status"] == "queued":
        worker = cockpit.AgentWorker(runtime, cockpit.gateway_model, cockpit.ToolExecutor(runtime, cockpit.handlers()))
        worker.run_with_retries(task_id, "codex-workbench-worker")
    return cockpit.task_details(task_id)


def pm_memory(arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = resolve_project(arguments)
    return cockpit.runtime().memory_action(project_id, str(arguments.get("action") or "context"), arguments)


TOOLS = {
    "list_agents": ("列出四个公开 Agent 及其可用模式。", lambda args: cockpit.catalog()["agents"], {"type": "object", "properties": {}}),
    "run_agent": ("在指定项目中用同一 AgentEngine 运行 Agent；project_id 必填，支持 inputs、材料、来源和会话 ID。", run_agent, {"type": "object", "required": ["project_id", "agent_id"], "properties": {"project_id": {"type": "string"}, "agent_id": {"type": "string"}, "mode": {"type": "string"}, "goal": {"type": "string"}, "decision_to_support": {"type": "string"}, "inputs": {"type": "object"}, "material_paths": {"type": "array", "items": {"type": "string"}}, "source": {"type": "string"}, "session_id": {"type": "string"}, "pm_confirmed": {"type": "boolean"}}}),
    "run_workflow": ("在指定项目中启动并运行 pm-idea-to-delivery；流程会在 PM 门禁处返回。", run_workflow, {"type": "object", "required": ["project_id", "goal", "decision_to_support"], "properties": {"project_id": {"type": "string"}, "goal": {"type": "string"}, "decision_to_support": {"type": "string"}}}),
    "get_agent_task": ("读取 Agent 的状态、结果、追问、审批和 Trace。", get_agent_task, {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}}}),
    "update_agent_task": ("提交 Agent 的追问答案或审批决定并继续运行。", update_agent_task, {"type": "object", "required": ["task_id", "action"], "properties": {"task_id": {"type": "string"}, "action": {"type": "string"}, "input_id": {"type": "string"}, "responses": {"type": "object"}, "approval_id": {"type": "string"}, "approved": {"type": "boolean"}}}),
    "pm_memory": ("读取或写入当前项目的跨会话 PM 记忆；原始对话追加保存，项目内容不跨项目共享。", pm_memory, {"type": "object", "required": ["project_id", "action"], "properties": {"project_id": {"type": "string"}, "action": {"enum": ["context", "search", "open_session", "append_turn", "propose_memory", "update_memory"]}, "query": {"type": "string"}, "limit": {"type": "integer"}, "source": {"type": "string"}, "session_id": {"type": "string"}, "session_db_id": {"type": "string"}, "role": {"type": "string"}, "content": {"type": "string"}, "scope": {"enum": ["project", "user"]}, "memory_type": {"type": "string"}, "confidence": {"type": "string"}, "confirm": {"type": "boolean"}, "memory_id": {"type": "string"}, "replacement_id": {"type": "string"}, "status": {"type": "string"}, "metadata": {"type": "object"}}}),
}


def respond(request_id: Any, result: Any = None, error: str = "") -> None:
    payload = {"jsonrpc": "2.0", "id": request_id}
    payload["error" if error else "result"] = {"code": -32000, "message": error} if error else result
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    request: dict[str, Any] = {}
    try:
        request = json.loads(line)
        method = request.get("method")
        if method == "initialize":
            respond(request.get("id"), {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "pm-workbench", "version": "2.3.0"}})
        elif method == "tools/list":
            respond(request.get("id"), {"tools": [{"name": name, "description": item[0], "inputSchema": item[2]} for name, item in TOOLS.items()]})
        elif method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            if name not in TOOLS:
                raise ValueError(f"未知工具: {name}")
            output = TOOLS[name][1](params.get("arguments") or {})
            respond(request.get("id"), {"content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False, indent=2)}]})
        elif request.get("id") is not None:
            respond(request.get("id"), {})
    except Exception as exc:
        if request.get("id") is not None:
            respond(request.get("id"), error=str(exc))

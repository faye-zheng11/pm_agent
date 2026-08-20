#!/usr/bin/env python3
"""Codex Plugin MCP：通过同一 AgentEngine 运行独立 Agent。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True


PACKAGE_DIR = Path(os.environ.get("PM_AGENT_PACKAGE_DIR") or Path(__file__).resolve().parents[1]).resolve()
PROJECT_DIR = Path(os.environ.get("PM_AGENT_PROJECT") or os.getcwd()).expanduser().resolve()
sys.path.insert(0, str(PACKAGE_DIR / "scripts"))
from standalone_server import Runner

runner = Runner(PACKAGE_DIR, PROJECT_DIR)


def run_agent(arguments: dict[str, Any]) -> dict[str, Any]:
    return runner.start({
        "mode": arguments.get("mode"),
        "inputs": arguments.get("inputs") or {},
        "material_paths": arguments.get("material_paths") or [],
        "source": arguments.get("source") or "codex",
        "session_id": arguments.get("session_id") or "",
    })


def get_agent_task(arguments: dict[str, Any]) -> dict[str, Any]:
    return runner.details(str(arguments.get("task_id") or ""))


def update_agent_task(arguments: dict[str, Any]) -> dict[str, Any]:
    return runner.update(arguments)


def pm_memory(arguments: dict[str, Any]) -> dict[str, Any]:
    return runner.memory(arguments)


TOOLS = {
    "run_agent": (
        "使用 Package 的完整 AgentEngine 启动 Agent；支持多步工具循环、结构化追问、审批、重试、项目记忆和 Trace。",
        run_agent,
        {"type":"object","required":["inputs"],"properties":{"mode":{"type":"string"},"inputs":{"type":"object"},"material_paths":{"type":"array","items":{"type":"string"}},"source":{"type":"string"},"session_id":{"type":"string"}}},
    ),
    "get_agent_task": (
        "读取 Agent 任务、运行状态、结果、追问、审批和 Trace。",
        get_agent_task,
        {"type":"object","required":["task_id"],"properties":{"task_id":{"type":"string"}}},
    ),
    "update_agent_task": (
        "提交 Agent 追问答案或批准/拒绝审批，并用同一 AgentEngine 继续运行。",
        update_agent_task,
        {"type":"object","required":["task_id","action"],"properties":{"task_id":{"type":"string"},"action":{"enum":["provide_input","decide_approval"]},"input_id":{"type":"string"},"responses":{"type":"object"},"approval_id":{"type":"string"},"approved":{"type":"boolean"}}},
    ),
    "pm_memory": (
        "读取或写入当前项目的跨会话 PM 记忆；原始对话追加保存，项目内容不跨项目共享。",
        pm_memory,
        {"type":"object","required":["action"],"properties":{"action":{"enum":["context","search","open_session","append_turn","propose_memory","update_memory"]},"query":{"type":"string"},"limit":{"type":"integer"},"source":{"type":"string"},"session_id":{"type":"string"},"session_db_id":{"type":"string"},"role":{"type":"string"},"content":{"type":"string"},"scope":{"enum":["project","user"]},"memory_type":{"type":"string"},"confidence":{"type":"string"},"confirm":{"type":"boolean"},"memory_id":{"type":"string"},"replacement_id":{"type":"string"},"status":{"type":"string"},"metadata":{"type":"object"}}},
    ),
}


def respond(request_id: Any, result: Any = None, error: str = "") -> None:
    value = {"jsonrpc": "2.0", "id": request_id}
    value["error" if error else "result"] = {"code": -32000, "message": error} if error else result
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    request: dict[str, Any] = {}
    try:
        request = json.loads(line)
        method = request.get("method")
        if method == "initialize":
            respond(request.get("id"), {"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"pm-agent-engine","version":"2.3.0"}})
        elif method == "tools/list":
            respond(request.get("id"), {"tools":[{"name":name,"description":item[0],"inputSchema":item[2]} for name,item in TOOLS.items()]})
        elif method == "tools/call":
            params = request.get("params") or {};name = params.get("name")
            if name not in TOOLS:raise ValueError(f"未知工具: {name}")
            output = TOOLS[name][1](params.get("arguments") or {})
            respond(request.get("id"), {"content":[{"type":"text","text":json.dumps(output,ensure_ascii=False,indent=2)}]})
        elif request.get("id") is not None:
            respond(request.get("id"), {})
    except Exception as exc:
        if request.get("id") is not None:respond(request.get("id"), error=str(exc))

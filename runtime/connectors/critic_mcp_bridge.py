#!/usr/bin/env python3
"""Small stdio MCP client used by the Cockpit data_gateway adapter.

The bridge reads the existing local MCP registration, never prints its env,
and keeps bind_project + query in the same gateway session.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and older: the fallback parser only reads this known MCP block.
    tomllib = None


def _configured_server() -> dict[str, object]:
    config_path = Path.home() / ".codex" / "config.toml"
    try:
        raw = config_path.read_text(encoding="utf-8")
        if tomllib is not None:
            config = tomllib.loads(raw)
        else:
            # Keep the bridge usable on older system Python versions without
            # adding a second TOML dependency to the workbench.
            import re
            match = re.search(r"(?ms)^\[mcp_servers\.critic_gateway\]\n(?P<body>.*?)(?=^\[|\Z)", raw)
            env_match = re.search(r"(?ms)^\[mcp_servers\.critic_gateway\.env\]\n(?P<body>.*?)(?=^\[|\Z)", raw)
            if not match:
                raise KeyError("mcp_servers.critic_gateway")
            def value(name: str, body: str) -> str:
                found = re.search(rf"(?m)^{re.escape(name)}\s*=\s*\"([^\"]*)\"", body)
                return found.group(1) if found else ""
            body = match.group("body")
            args_match = re.search(r"(?m)^args\s*=\s*\[\s*\"([^\"]*)\"\s*\]", body)
            env_body = env_match.group("body") if env_match else ""
            config = {"mcp_servers": {"critic_gateway": {
                "command": value("command", body),
                "args": [args_match.group(1)] if args_match else [],
                "env": {key: value(key, env_body) for key in ("GATEWAY_MYSQL_HOST", "GATEWAY_MYSQL_PORT", "GATEWAY_MYSQL_USER", "GATEWAY_MYSQL_PASS", "CRITIC_OPERATOR")},
            }}}
        item = config["mcp_servers"]["critic_gateway"]
    except (OSError, KeyError, ValueError, getattr(tomllib, "TOMLDecodeError", ValueError)) as exc:
        raise RuntimeError("未找到可用的 critic_gateway MCP 配置") from exc
    if not isinstance(item, dict):
        raise RuntimeError("critic_gateway MCP 配置格式无效")
    return item


def _server_python() -> str:
    """优先复用数据 Agent 注册时的 Python 环境，避免系统 Python 缺 mcp。"""
    item = _configured_server()
    command = str(item.get("command") or "").strip()
    args = item.get("args") or []
    candidates: list[Path] = []
    direct = Path(command).expanduser()
    if direct.is_file():
        candidates.append(direct)
    cwd = Path(str(item.get("cwd") or "")).expanduser()
    if cwd.is_dir():
        candidates.append(cwd / ".venv" / "bin" / "python")
    if isinstance(args, list):
        for value in args:
            script = Path(str(value)).expanduser()
            if script.suffix == ".py" and script.is_file():
                candidates.extend((
                    script.parent.parent / ".venv" / "bin" / "python",
                    script.parent / ".venv" / "bin" / "python",
                ))
                break
    resolved = shutil.which(command)
    if resolved:
        candidates.append(Path(resolved))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def _reexec_with_server_python() -> None:
    if importlib.util.find_spec("mcp") is not None:
        return
    candidate = _server_python()
    if candidate != sys.executable:
        os.execv(candidate, [candidate, *sys.argv])
    raise RuntimeError(
        "当前 Python 和 critic_gateway 注册环境都没有 mcp 依赖；请先安装数据 Agent，或重跑其安装脚本"
    )


_reexec_with_server_python()

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def load_server() -> StdioServerParameters:
    item = _configured_server()
    command = str(item.get("command") or "").strip()
    args = item.get("args") or []
    env = item.get("env") or {}
    if not command or not isinstance(args, list) or not isinstance(env, dict):
        raise RuntimeError("critic_gateway MCP 配置不完整")
    return StdioServerParameters(
        command=command,
        args=[str(value) for value in args],
        env={**os.environ, **{str(key): str(value) for key, value in env.items()}},
    )


def text_content(result) -> str:
    if getattr(result, "isError", False):
        raise RuntimeError("critic_gateway 返回错误")
    parts = [block.text for block in result.content if getattr(block, "type", "") == "text"]
    return "\n".join(parts)


async def invoke(action: str, project: str, sql: str) -> dict[str, object]:
    async with stdio_client(load_server()) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            if action == "list_projects":
                listed = await session.call_tool("list_projects", {})
                return {"ok": True, "action": action, "result": text_content(listed)}
            bound = await session.call_tool("bind_project", {"project_code": project})
            binding = text_content(bound)
            if "已绑定" not in binding:
                raise RuntimeError(binding)
            if action == "bind_project":
                return {
                    "ok": True,
                    "action": action,
                    "data_agent": "critic-analyze",
                    "binding": binding,
                    "project_code": project.upper(),
                    "protocol": "list_projects -> bind_project -> query",
                }
            queried = await session.call_tool("query", {"sql": sql})
            result = text_content(queried)
            if "已拒绝" in result or "执行错误" in result:
                raise RuntimeError(result)
            return {
                "ok": True,
                "action": action,
                "data_agent": "critic-analyze",
                "binding": binding,
                "project_code": project.upper(),
                "sql": sql,
                "result": result,
                "protocol": "list_projects -> bind_project -> query",
            }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("list_projects", "bind_project", "query"), required=True)
    parser.add_argument("--project", default="")
    parser.add_argument("--sql", default="")
    args = parser.parse_args()
    if args.action in {"bind_project", "query"} and not args.project.strip():
        parser.error(f"{args.action} 需要 --project")
    if args.action == "query" and not args.sql.strip():
        parser.error("query 需要 --sql")
    try:
        print(json.dumps(asyncio.run(invoke(args.action, args.project, args.sql)), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Small stdio MCP client used by the Cockpit data_gateway adapter.

The bridge reads the existing local MCP registration, never prints its env,
and keeps bind_project + query in the same gateway session.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tomllib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def load_server() -> StdioServerParameters:
    config_path = Path.home() / ".codex" / "config.toml"
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        item = config["mcp_servers"]["critic_gateway"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError("未找到可用的 critic_gateway MCP 配置") from exc
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
            queried = await session.call_tool("query", {"sql": sql})
            result = text_content(queried)
            if "已拒绝" in result or "执行错误" in result:
                raise RuntimeError(result)
            return {"ok": True, "action": action, "binding": binding, "result": result}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("list_projects", "query"), required=True)
    parser.add_argument("--project", default="")
    parser.add_argument("--sql", default="")
    args = parser.parse_args()
    if args.action == "query" and (not args.project.strip() or not args.sql.strip()):
        parser.error("query 需要 --project 和 --sql")
    try:
        print(json.dumps(asyncio.run(invoke(args.action, args.project, args.sql)), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())

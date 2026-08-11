#!/usr/bin/env python3
import os
from pathlib import Path

os.environ.setdefault("PM_AGENT_PACKAGE_DIR", str(Path(__file__).resolve().parents[1]))

local = Path(__file__).with_name("package_mcp_runtime.py")
shared = Path(__file__).resolve().parents[2] / "_shared" / "package_mcp_runtime.py"
source = local if local.is_file() else shared
exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"))

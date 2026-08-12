#!/usr/bin/env python3
"""PM AI 工作台七核心 HTTP 服务。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

try:
    from scripts.agent_runtime import AgentRuntime, AgentWorker, ContractError, StateTransitionError, ToolExecutor, WorkflowScheduler, safe_project_path
except ImportError:
    from agent_runtime import AgentRuntime, AgentWorker, ContractError, StateTransitionError, ToolExecutor, WorkflowScheduler, safe_project_path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from gateway_client import GatewayError, chat_completion, post_json

HTML_FILE = ROOT / "pm-workbench.html"
CONFIG_FILE = Path.home() / ".config" / "pm-workbench" / "gateway.json"
KEYCHAIN_SERVICE = "pm-workbench-ai-gateway"
KEYCHAIN_ACCOUNT = "default"
CODEX_AUTH_FILE = Path.home() / ".codex" / "auth.json"
DEFAULT_GATEWAY = {
    "base_url": "https://aigateway-infra.oppaya.app",
    "model": "gpt-5.6-sol",
    "reasoning_effort": "high",
    "allow_fixed_gateway_tls_exception": True,
}
CORE_PACKAGES = (
    "opportunity-researcher",
    "product-shaper",
    "user-experience-reviewer",
    "independent-critic",
)
CORE_SKILLS = ("pmf-bet-brief", "prd-writing")
CORE_WORKFLOW = "pm-idea-to-delivery"
_runtime: AgentRuntime | None = None
_runtime_lock = threading.Lock()
_critic_gateway_probe: tuple[float, bool] | None = None


def now_date() -> str:
    return time.strftime("%Y-%m-%d")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def gateway_config() -> dict[str, Any]:
    stored = read_json(CONFIG_FILE, {})
    config = {**DEFAULT_GATEWAY, **(stored if isinstance(stored, dict) else {})}
    config["base_url"] = str(config.get("base_url") or DEFAULT_GATEWAY["base_url"]).rstrip("/")
    config["model"] = str(config.get("model") or DEFAULT_GATEWAY["model"])
    config["reasoning_effort"] = str(config.get("reasoning_effort") or "high")
    return config


def gateway_token() -> str:
    env_token = os.environ.get("PM_WORKBENCH_API_KEY", "").strip()
    if env_token:
        return env_token
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    auth = read_json(CODEX_AUTH_FILE, {})
    return str(auth.get("OPENAI_API_KEY") or "").strip() if isinstance(auth, dict) else ""


def gateway_status() -> dict[str, Any]:
    config = gateway_config()
    parsed = urllib.parse.urlparse(config["base_url"])
    fixed_gateway = parsed.hostname == "aigateway-infra.oppaya.app"
    tls_exception = fixed_gateway and bool(config.get("allow_fixed_gateway_tls_exception"))
    return {
        "configured": bool(gateway_token()),
        "base_url": config["base_url"],
        "model": config["model"],
        "reasoning_effort": config["reasoning_effort"],
        "tls": {
            "verified_by_system_ca": not tls_exception,
            "fixed_gateway_exception": tls_exception,
            "message": "证书未由系统 CA 验证，仅对固定公司网关启用本机例外" if tls_exception else "使用系统 CA 验证",
        },
    }


def gateway_ssl(config: dict[str, Any]) -> ssl.SSLContext:
    parsed = urllib.parse.urlparse(config["base_url"])
    if parsed.hostname == "aigateway-infra.oppaya.app" and config.get("allow_fixed_gateway_tls_exception"):
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def gateway_model(system: str, messages: list[dict[str, str]], max_tokens: int) -> str:
    config = gateway_config()
    token = gateway_token()
    if not token:
        raise RuntimeError("未找到可用网关凭据，请运行 setup.command 或登录 Codex")
    try:
        return chat_completion(
            base_url=config["base_url"], model=config["model"],
            reasoning_effort=config["reasoning_effort"], token=token,
            system=system, messages=messages, max_tokens=max_tokens,
            allow_fixed_gateway_tls_exception=bool(config.get("allow_fixed_gateway_tls_exception")),
            timeout_seconds=300,
        )
    except GatewayError as exc:
        raise RuntimeError(str(exc)) from exc


def tavily_key() -> str:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if key:
        return key
    path = Path.home() / ".config" / "pm-workbench" / "tavily-api-key"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def tavily(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = tavily_key()
    if not key:
        raise RuntimeError("公开网页研究尚未配置 Tavily；请设置 TAVILY_API_KEY 或本机 tavily-api-key")
    try:
        return post_json("https://api.tavily.com/" + endpoint, {"api_key": key, **payload}, timeout_seconds=60)
    except GatewayError as exc:
        raise RuntimeError(f"公开网页研究失败：{exc}") from exc


def web_research(_task: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "search")
    if action == "search":
        query = str(arguments.get("query") or "").strip()
        if len(query) < 2:
            raise ContractError("web_research.search query 不能为空")
        value = tavily("search", {
            "query": query,
            "search_depth": "advanced",
            "topic": str(arguments.get("topic") or "general"),
            "max_results": min(max(int(arguments.get("max_results") or 6), 1), 8),
            "include_raw_content": False,
        })
        return {"action": action, "query": query, "results": value.get("results") or [], "accessed_at": now_date()}
    if action == "extract":
        url = str(arguments.get("url") or "").strip()
        if not re.fullmatch(r"https?://[^\s]+", url):
            raise ContractError("web_research.extract 需要公开 http(s) URL")
        value = tavily("extract", {"urls": [url], "extract_depth": "advanced"})
        return {"action": action, "url": url, "results": value.get("results") or [], "accessed_at": now_date()}
    raise ContractError(f"web_research 不支持 action: {action}")


def social_ingest(task: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    source = str(arguments.get("source") or "reddit")
    script = ROOT / "agent-packages" / "opportunity-researcher" / "scripts" / "social_ingest.py"
    command = [os.environ.get("PYTHON", "python3"), str(script)]
    query = str(arguments.get("query") or "").strip()
    if source == "reddit":
        if len(query) < 2:
            raise ContractError("social_ingest.query 不能为空")
        limit = min(max(int(arguments.get("limit") or 8), 1), 20)
        command += ["reddit", query, "--limit", str(limit)]
    elif source in {"x", "xiaohongshu", "mediacrawler"}:
        target = str(arguments.get("path") or "").strip()
        allowed = set(task.get("source_artifacts") or [])
        if not target or target not in allowed:
            raise ContractError("X/小红书必须先上传导出文件，并把该文件作为任务材料授权给 Agent")
        project = runtime().projects.resolve(task["project_id"])
        normalized = target
        prefix = f"projects/{project['path'].name}/"
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
        path = safe_project_path(project["path"], normalized, allow_runtime=True)
        if not path.is_file() or path.suffix.lower() != ".json":
            raise ContractError("社媒导入文件必须是任务已授权的 JSON 导出文件")
        command += ["x" if source == "x" else "mediacrawler", str(path)]
    else:
        raise ContractError("social_ingest.source 只能是 reddit、x 或 xiaohongshu")
    result = subprocess.run(
        command,
        cwd=ROOT, capture_output=True, text=True, timeout=90, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "社媒采集失败")
    return {"source": source, "query": query, "posts": json.loads(result.stdout), "accessed_at": now_date(), "login_boundary": "仅处理公开 Reddit 或用户主动导出的 X/小红书材料；不接管账号登录"}


def demo_html(task: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    spec = str(arguments.get("spec") or arguments.get("brief") or "").strip()
    if not spec:
        raise ContractError("demo_html.spec 不能为空")
    key = gateway_token()
    if not key:
        raise ContractError("demo_html 需要可用网关凭据")
    script = ROOT / "agent-packages" / "product-shaper" / "scripts" / "demo_gen.py"
    if not script.is_file():
        raise ContractError("demo_gen.py 不存在，不能生成 HTML Demo")
    project = runtime().projects.resolve(task["project_id"])
    output_dir = project["path"] / ".workbench" / "demos"
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(spec.encode("utf-8")).hexdigest()[:16]
    output_file = output_dir / f"{digest}.html"
    environment = dict(os.environ, PM_WORKBENCH_API_KEY=key)
    completed = subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(script), spec, str(output_file)],
        cwd=ROOT, capture_output=True, text=True, timeout=290, check=False, env=environment,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "demo 生成失败")
    try:
        generated = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        generated = {"ok": output_file.is_file(), "bytes": output_file.stat().st_size if output_file.is_file() else 0}
    if not output_file.is_file() or output_file.stat().st_size < 500 or not generated.get("ok"):
        detail = str(generated.get("error") or generated.get("message") or "网关没有返回有效 HTML")
        raise RuntimeError(f"demo 生成未完成：{detail}")
    relative = output_file.relative_to(ROOT).as_posix()
    generated.update({"ok": output_file.is_file(), "status": "completed", "artifact": relative, "path": relative, "label": "concept_validation"})
    return generated


def authorized_html_material(task: dict[str, Any], target: str) -> tuple[dict[str, Any], Path, str]:
    project = runtime().projects.resolve(task["project_id"])
    allowed = set(task.get("source_artifacts") or [])
    normalized = target
    prefix = f"projects/{project['path'].name}/"
    if normalized.startswith(prefix):
        normalized = normalized[len(prefix):]
    candidates = {target, normalized, prefix + normalized}
    if not candidates.intersection(allowed):
        raise ContractError("只能读取任务已授权的 HTML 材料")
    path = (project["path"] / normalized).resolve()
    if not path.is_relative_to(project["path"].resolve()) or not path.is_file() or path.suffix.lower() not in {".html", ".htm"}:
        raise ContractError("目标必须是当前项目内已授权的 HTML 文件")
    return project, path, normalized


def persona_review(task: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    target = str(arguments.get("target") or "").strip()
    persona = str(arguments.get("persona") or "团粉").strip()
    if not target:
        raise ContractError("persona_review.target 不能为空")
    _, path, normalized = authorized_html_material(task, target)
    key = gateway_token()
    script = ROOT / "agent-packages" / "user-experience-reviewer" / "scripts" / "ux_review.py"
    if not key or not script.is_file():
        raise ContractError("persona_review 需要可用网关凭据和 ux_review.py")
    environment = dict(os.environ, PM_WORKBENCH_API_KEY=key)
    completed = subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(script), str(path), persona],
        cwd=ROOT, capture_output=True, text=True, timeout=260, check=False, env=environment,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "persona review 失败")
    return {"ok": True, "status": "completed", "target": normalized, "persona": persona, "review": completed.stdout.strip()}


def critic_gateway_available() -> bool:
    global _critic_gateway_probe
    if _critic_gateway_probe and time.time() - _critic_gateway_probe[0] < 30:
        return _critic_gateway_probe[1]
    config = Path.home() / ".codex" / "config.toml"
    try:
        text = config.read_text(encoding="utf-8")
        if "[mcp_servers.critic_gateway]" not in text:
            _critic_gateway_probe = (time.time(), False)
            return False
        bridge = ROOT / "runtime" / "connectors" / "critic_mcp_bridge.py"
        if not bridge.is_file():
            _critic_gateway_probe = (time.time(), False)
            return False
        result = subprocess.run(
            [sys.executable, str(bridge), "--action", "list_projects"],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
        )
        value = json.loads(result.stdout)
        available = result.returncode == 0 and isinstance(value, dict) and value.get("ok") is True
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        available = False
    _critic_gateway_probe = (time.time(), available)
    return available


def data_gateway(task: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "query").strip()
    if action not in {"list_projects", "query"}:
        raise ContractError("data_gateway.action 只能是 list_projects 或 query")
    binding = ""
    if action == "query":
        project = runtime().projects.resolve(task["project_id"])
        config = runtime().registry.project_config(project)
        binding = str((config.get("tool_overrides", {}).get("data_gateway") or {}).get("binding") or "").strip()
        requested_binding = str(arguments.get("project_code") or "").strip()
        if requested_binding:
            binding = requested_binding
        if not binding:
            raise ContractError(
                f"项目 {task['project_id']} 未配置 data_gateway binding；请先用 list_projects 查看可用数据项目，再请 PM 明确选择绑定"
            )
    sql = str(arguments.get("sql") or "").strip()
    if action == "query" and (not re.match(r"(?is)^\s*(select|with)\b", sql) or re.search(r"(?is)\b(insert|update|delete|drop|alter|create|truncate)\b", sql)):
        raise ContractError("data_gateway 只允许 SELECT / WITH 只读查询")
    command = [os.environ.get("PYTHON", "python3"), str(ROOT / "runtime" / "connectors" / "critic_mcp_bridge.py"), "--action", action]
    if action == "query":
        command += ["--project", binding, "--sql", sql]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("critic_gateway bridge 返回格式无效") from exc
    if result.returncode != 0 or not value.get("ok"):
        raise RuntimeError(str(value.get("error") or "critic_gateway 调用失败"))
    return value


def runtime() -> AgentRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = AgentRuntime(ROOT)
    return _runtime


def available_tools() -> set[str]:
    tools = {"project_memory", "artifact_store", "signal_ledger", "material_inspector", "browser_review", "finding_ledger", "demo_builder"}
    if gateway_token() and (ROOT / "agent-packages" / "product-shaper" / "scripts" / "demo_gen.py").is_file():
        tools.add("demo_html")
    if gateway_token() and (ROOT / "agent-packages" / "user-experience-reviewer" / "scripts" / "ux_review.py").is_file():
        tools.add("persona_review")
    if tavily_key():
        tools.update({"web_research", "social_ingest"})
    if critic_gateway_available():
        tools.add("data_gateway")
    return tools


def handlers() -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "demo_html" in available_tools():
        result["demo_html"] = demo_html
    if "persona_review" in available_tools():
        result["persona_review"] = persona_review
    if tavily_key():
        result.update({"web_research": web_research, "social_ingest": social_ingest})
    if critic_gateway_available():
        result["data_gateway"] = data_gateway
    return result


def task_details(task_id: str) -> dict[str, Any]:
    rt = runtime()
    task = rt.store.get(task_id)
    task["events"] = rt.store.events(task_id)
    task["input_requests"] = rt.store.input_requests(task_id)
    task["approvals"] = rt.store.approvals(task_id)
    return task


def run_task(task_id: str) -> None:
    rt = runtime()
    worker = AgentWorker(rt, gateway_model, ToolExecutor(rt, handlers()))
    try:
        worker.run_with_retries(task_id, "workbench-worker")
    except Exception as exc:
        try:
            rt.store.record_event(task_id, "worker.error", "workbench-worker", {
                "category": getattr(exc, "category", "worker"),
                "reason": str(exc)[:1000],
            })
        except Exception:
            pass
        return


def run_workflow(run_id: str) -> None:
    rt = runtime()
    scheduler = WorkflowScheduler(rt, available_tools())
    for _ in range(200):
        run = scheduler.advance(run_id)
        if run["status"] in {"completed", "blocked", "failed", "cancelled", "waiting_approval", "waiting_input"}:
            return
        tasks = scheduler.runnable_tasks(run_id)
        if not tasks:
            return
        for task in tasks:
            run_task(task["id"])


def spawn(target: Any, *args: Any) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()


def project_id_from(handler: SimpleHTTPRequestHandler, data: dict[str, Any] | None = None) -> str:
    project_id = handler.headers.get("X-Project-ID", "").strip() or str((data or {}).get("project_id") or "").strip()
    if not project_id:
        raise ContractError("请求缺少 X-Project-ID")
    runtime().projects.resolve(project_id)
    return project_id


def project_summary(project: dict[str, Any]) -> dict[str, Any]:
    project_path: Path = project["path"]
    yaml_text = (project_path / "project.yaml").read_text(encoding="utf-8", errors="replace")
    def scalar(key: str) -> str:
        match = re.search(rf"(?m)^{re.escape(key)}:\s*['\"]?([^\n#'\"]*)", yaml_text)
        return match.group(1).strip() if match else ""
    return {
        "id": project["id"], "name": project["name"], "stage": scalar("stage"),
        "version": scalar("version"), "active_bet": scalar("active_bet"),
        "active_feature": scalar("active_feature"), "objective": scalar("objective"),
        "temporary": project["id"].startswith("scratch-") or scalar("status") == "temporary",
    }


def imports_path(project: dict[str, Any]) -> Path:
    return project["path"] / ".workbench" / "imports" / "index.json"


def intake_path(project: dict[str, Any]) -> Path:
    return project["path"] / ".workbench" / "project-intake.json"


def project_version(project: dict[str, Any]) -> str:
    summary = project_summary(project)
    return str(summary.get("version") or "v0.1").strip() or "v0.1"


def material_version(project: dict[str, Any], item: dict[str, Any]) -> str:
    return str(item.get("material_version") or project_version(project)).strip() or project_version(project)


def material_is_active(item: dict[str, Any]) -> bool:
    return str(item.get("status") or "").strip() not in {"已删除", "已被替换"}


def write_imports(project: dict[str, Any], document: dict[str, Any]) -> None:
    path = imports_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_intake_stale(project: dict[str, Any], reason: str) -> None:
    path = intake_path(project)
    document = intake_document(project)
    if str(document.get("analysis") or "").strip():
        document["status"] = "needs_analysis"
        document["draft_stale"] = True
        document["stale_reason"] = reason
    else:
        document["status"] = "needs_analysis"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_material_version(value: Any, fallback: str) -> str:
    version = str(value or fallback).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,31}", version):
        raise ContractError("资料版本需为 1-32 位字母、数字、点、下划线、空格或连字符")
    return version


def normalize_upload_name(raw_name: Any) -> str:
    raw = str(raw_name or "").strip().replace("\\", "/")
    name = Path(raw).name
    if not name or name in {".", ".."} or len(name) > 120 or any(ord(char) < 32 for char in name):
        raise ContractError("材料文件名无效")
    return name


def record_import(project: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    path = imports_path(project)
    document = read_json(path, {"schema_version": "1.1", "items": []})
    if not isinstance(document, dict):
        document = {"schema_version": "1.1", "items": []}
    items = document.get("items") if isinstance(document.get("items"), list) else []
    item = {
        "id": uuid.uuid4().hex[:12],
        "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        **item,
    }
    item["material_version"] = normalize_material_version(item.get("material_version"), project_version(project))
    items.append(item)
    document["schema_version"] = "1.1"
    document["items"] = items[-500:]
    write_imports(project, document)
    return item


def find_import_item(project: dict[str, Any], item_id: str) -> tuple[dict[str, Any], dict[str, Any], int]:
    document = read_json(imports_path(project), {"schema_version": "1.1", "items": []})
    items = document.get("items", []) if isinstance(document, dict) else []
    for index, item in enumerate(items):
        if str(item.get("id") or "") == item_id:
            return document, item, index
    raise ContractError("资料不存在或已被移除")


def update_import_item(project: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    item_id = str(data.get("id") or "").strip()
    if not item_id:
        raise ContractError("资料 ID 不能为空")
    document, item, index = find_import_item(project, item_id)
    action = str(data.get("action") or "").strip()
    if action == "delete":
        if not material_is_active(item):
            raise ContractError("资料已经不在当前资料范围内")
        item["status"] = "已删除"
        item["deleted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    elif action == "restore":
        if str(item.get("status") or "") != "已删除":
            raise ContractError("只有已删除资料可以恢复")
        item["status"] = "已导入"
        item.pop("deleted_at", None)
    elif action == "update_meta":
        name = normalize_upload_name(data.get("name") or item.get("name"))
        item["name"] = name
        item["material_version"] = normalize_material_version(data.get("material_version"), material_version(project, item))
        if data.get("description") is not None:
            item["description"] = str(data.get("description") or "").strip()[:500]
    else:
        raise ContractError("资料更新动作无效")
    document["items"][index] = item
    document["schema_version"] = "1.1"
    write_imports(project, document)
    mark_intake_stale(project, f"资料“{item.get('name') or item_id}”已发生变化")
    return item


def classify_source_url(url: str) -> tuple[str, str]:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if "figma.com" in host:
        return "figma", "待连接或授权"
    if "feishu.cn" in host or "feishu.com" in host or "larksuite.com" in host:
        return "feishu", "待连接或授权"
    return "external_link", "待读取"


def intake_document(project: dict[str, Any]) -> dict[str, Any]:
    value = read_json(intake_path(project), {})
    if not isinstance(value, dict):
        value = {}
    value["schema_version"] = "1.1"
    value.setdefault("status", "not_started")
    value.setdefault("analysis", "")
    value.setdefault("pm_notes", [])
    value.setdefault("analysis_version", project_version(project))
    value.setdefault("analysis_history", [])
    value.setdefault("confirmed_analysis", "")
    value.setdefault("confirmed_version", "")
    value.setdefault("draft_stale", False)
    value.setdefault("stale_reason", "")
    value.setdefault("rejection_reason", "")
    return value


def _read_intake_materials(project: dict[str, Any], selected_version: str = "") -> tuple[str, list[str], list[dict[str, Any]]]:
    imports = read_json(imports_path(project), {"items": []})
    items = imports.get("items", []) if isinstance(imports, dict) else []
    blocks: list[str] = []
    limitations: list[str] = []
    selected_items: list[dict[str, Any]] = []
    used = 0
    text_suffixes = {".md", ".txt", ".json", ".yaml", ".yml", ".html", ".htm", ".csv"}
    for item in items[-80:]:
        if not material_is_active(item):
            continue
        if selected_version and material_version(project, item) != selected_version:
            continue
        selected_items.append(item)
        relative = str(item.get("path") or "")
        if not relative:
            if item.get("url"):
                limitations.append(f"外部来源待授权或读取：{item['url']}")
            continue
        try:
            path = safe_project_path(project["path"], relative, allow_runtime=True)
        except Exception:
            limitations.append(f"路径未读取：{relative}")
            continue
        if not path.is_file():
            limitations.append(f"文件不存在：{relative}")
            continue
        if path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as archive:
                    names = [name for name in archive.namelist() if not name.endswith("/")]
                    blocks.append(f"## 压缩包 {item.get('original_path') or item.get('name') or path.name}\n包含文件：{', '.join(names[:80])}")
                    for name in names:
                        suffix = Path(name).suffix.lower()
                        if suffix not in text_suffixes or used >= 50000 or name.startswith(("/", "../")):
                            continue
                        try:
                            content = archive.read(name).decode("utf-8", errors="replace")[:10000]
                        except Exception:
                            continue
                        block = f"### {name}\n{content}"
                        blocks.append(block)
                        used += len(block)
            except zipfile.BadZipFile:
                limitations.append(f"压缩包无法读取：{relative}")
            continue
        if path.suffix.lower() in text_suffixes:
            content = path.read_text(encoding="utf-8", errors="replace")[:12000]
            block = f"## {item.get('original_path') or item.get('name') or relative}\n{content}"
            blocks.append(block)
            used += len(block)
        elif path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            blocks.append(f"## 图片 {item.get('original_path') or item.get('name') or relative}\n仅收到图片文件，尚未进行像素级视觉理解。")
        else:
            limitations.append(f"暂不自动解析：{relative}")
        if used >= 60000:
            limitations.append("资料内容超过本次分析上下文上限，后续文件未全部展开。")
            break
    return "\n\n".join(blocks)[:70000], limitations, selected_items


def analyze_project_intake(project_id: str, requested_version: Any = "") -> dict[str, Any]:
    project = runtime().projects.resolve(project_id)
    document = intake_document(project)
    if requested_version:
        document["analysis_version"] = normalize_material_version(requested_version, project_version(project))
    selected_version = normalize_material_version(document.get("analysis_version"), project_version(project))
    material_text, limitations, selected_items = _read_intake_materials(project, selected_version)
    imports = read_json(imports_path(project), {"items": []})
    items = imports.get("items", []) if isinstance(imports, dict) else []
    links = [str(item.get("url")) for item in selected_items if item.get("url")]
    pm_notes = document.get("pm_notes") if isinstance(document.get("pm_notes"), list) else []
    if not material_text and not links and not pm_notes:
        raise ContractError("当前项目还没有可分析资料，请先上传文件或登记链接")
    prompt = (
        "你是 PM 工作台的项目资料整理助手，不是对外 Agent。请根据用户上传的项目资料，给 PM 一份中文的‘项目现状草稿’，不能把推测写成事实。\n"
        "请按以下标题输出：1. 我看到了什么 2. 可能的产品与用户 3. 已有产物和当前进度 4. 事实 / 推测 / 缺口 5. 我需要 PM 补充确认的 3-8 个问题 6. 建议下一步。\n"
        "每个关键判断尽量引用资料文件名；无法读取的链接或文件必须列入限制。明确说明这只是待 PM 确认草稿，不要替 PM 修改正式项目结论。\n\n"
        f"项目：{project['name']}（{project_id}）\n"
        f"本次分析资料版本：{selected_version}\n"
        f"已登记外部链接：{json.dumps(links, ensure_ascii=False)}\n"
        f"资料内容：\n{material_text or '暂无可直接展开的文字内容'}\n"
        f"PM 已补充说明：\n{json.dumps(pm_notes[-12:], ensure_ascii=False)}\n"
        f"当前确定性读取限制：{json.dumps(limitations, ensure_ascii=False)}"
    )
    analysis = gateway_model(
        "你负责整理项目上下文。保持事实边界，使用普通中文，输出可供 PM 审阅的结构化草稿。",
        [{"role": "user", "content": prompt}],
        3500,
    )
    if str(document.get("analysis") or "").strip():
        history = document.get("analysis_history") if isinstance(document.get("analysis_history"), list) else []
        history.append({
            "analysis": document.get("analysis"),
            "status": document.get("status", "draft"),
            "version": document.get("analysis_version", selected_version),
            "analyzed_at": document.get("analyzed_at", ""),
            "rejection_reason": document.get("rejection_reason", ""),
        })
        document["analysis_history"] = history[-20:]
    document.update({
        "status": "draft",
        "analysis": analysis,
        "limitations": limitations,
        "source_count": len(selected_items),
        "analyzed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "confirmed_at": document.get("confirmed_at", ""),
        "draft_stale": False,
        "stale_reason": "",
        "rejection_reason": "",
    })
    intake_path(project).parent.mkdir(parents=True, exist_ok=True)
    intake_path(project).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def project_overview(project_id: str) -> dict[str, Any]:
    rt = runtime()
    project = rt.projects.resolve(project_id)
    summary = project_summary(project)
    imports = read_json(imports_path(project), {"items": []})
    items = imports.get("items", []) if isinstance(imports, dict) else []
    active_items = [item for item in items if material_is_active(item)]
    versions = sorted({material_version(project, item) for item in active_items} | {project_version(project)})
    tasks = rt.store.list(project_id=project_id)
    runs = WorkflowScheduler(rt, available_tools()).list(project_id)
    active_run = next((run for run in runs if run.get("status") in {"running", "waiting_input", "waiting_approval"}), None)
    current_step = "尚未开始"
    current_detail = "可以从找机会或做产品开始"
    if active_run:
        nodes = active_run.get("nodes") or {}
        active_node = next((node for node in nodes.values() if node.get("status") in {"running", "waiting_input", "waiting_approval"}), None)
        current_step = str((active_node or {}).get("label") or (active_node or {}).get("id") or "完整流程运行中")
        current_detail = "完整流程正在等待 Agent 或 PM 门禁"
    elif tasks:
        latest = tasks[0]
        task_labels = {
            "opportunity.scan": "找机会 · 公开研究",
            "opportunity.new_project": "找机会 · 新项目方向",
            "opportunity.current_product": "找机会 · 迭代机会",
            "product.shape": "做产品 · 产品方案",
            "product.feature": "做产品 · 功能方案",
            "product.prd": "做产品 · PRD",
            "prototype.concept": "做产品 · 概念 Demo",
            "ux.demo": "用户试用 · HTML Demo",
            "review.project": "独立评审 · 项目诊断",
            "gate.verdict": "独立评审 · 快速评审",
        }
        current_step = task_labels.get(latest.get("task_type"), latest.get("assigned_agent") or "Agent 任务")
        current_detail = f"最近任务：{latest.get('status', '未知')}"
    stage_labels = {"discovery": "探索期", "validation": "验证期", "delivery": "交付期", "iteration": "迭代期", "maintenance": "维护期"}
    return {
        "project": summary,
        "stage": {"value": summary.get("stage") or "unknown", "label": stage_labels.get(summary.get("stage"), "待确认"), "basis": "来自 project.yaml；若已有运行记录，当前任务单独展示"},
        "current": {"step": current_step, "detail": current_detail, "active_run_id": active_run.get("id") if active_run else ""},
        "materials": {
            "count": len(active_items),
            "items": list(reversed(active_items[-60:])),
            "sources": [item for item in reversed(active_items) if item.get("kind") in {"figma", "feishu", "external_link"}][:10],
            "versions": versions,
            "current_version": project_version(project),
        },
        "tasks": tasks[:10],
        "workflow_runs": runs[:5],
        "next_action": current_detail if active_run or tasks else "先补充项目资料，或启动找机会 / 做产品",
    }


def create_project(data: dict[str, Any]) -> dict[str, Any]:
    temporary = bool(data.get("temporary"))
    project_id = str(data.get("id") or "").strip().lower()
    name = str(data.get("name") or "").strip()
    if temporary and not project_id:
        project_id = "scratch-" + uuid.uuid4().hex[:10]
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", project_id):
        raise ContractError("项目 ID 需为 2-40 位小写字母、数字或连字符")
    if temporary and not name:
        name = "临时工作区"
    if not name:
        raise ContractError("项目名称不能为空")
    target = ROOT / "projects" / project_id
    if target.exists():
        raise ContractError(f"项目已存在: {project_id}")
    shutil.copytree(ROOT / "projects" / "_template", target)
    replacements = {
        "HOME.md": [("# 项目首页", f"# {name}")],
        "manifest.yaml": [("name: \"新项目\"", f"name: {json.dumps(name, ensure_ascii=False)}"), ("created_at: \"\"", f"created_at: \"{now_date()}\"")],
        "project.yaml": [("project: \"replace-me\"", f"project: \"{project_id}\"")],
    }
    for relative, pairs in replacements.items():
        path = target / relative
        text = path.read_text(encoding="utf-8")
        for old, new in pairs:
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
    if temporary:
        manifest = target / "manifest.yaml"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace("status: discovery", "status: temporary"), encoding="utf-8")
        brain = target / "project.yaml"
        brain.write_text(brain.read_text(encoding="utf-8").replace("stage: discovery", "stage: discovery\nstatus: temporary"), encoding="utf-8")
    config = read_json(target / "agent-config.json", {})
    config["project_id"] = project_id
    (target / "agent-config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    global _runtime
    with _runtime_lock:
        _runtime = None
    return project_summary(runtime().projects.resolve(project_id))


def catalog() -> dict[str, Any]:
    rt = runtime()
    agent_items = []
    tool_state = available_tools()
    for package_id in CORE_PACKAGES:
        package = rt.registry.packages[package_id]
        agent_items.append({
            "id": package_id, "runtime_agent_id": package["runtime_agent_id"], "type": "Agent",
            "name": package["name"], "version": package["version"], "mission": package["mission"],
            "modes": package["modes"], "inputs": package["inputs"], "outputs": package["outputs"],
            "core_skills": package["core_skills"],
            "tools": [{"id": tool, "available": tool in tool_state} for tool in package["tools"]],
            "status": "可运行" if gateway_token() else "需要配置网关",
        })
    skill_items = []
    for skill_id in CORE_SKILLS:
        first = (ROOT / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8").splitlines()
        description = next((line.split(":", 1)[1].strip() for line in first if line.startswith("description:")), "")
        skill_items.append({"id": skill_id, "type": "Skill", "name": skill_id, "description": description, "status": "可调用"})
    workflow = rt.registry.workflows[CORE_WORKFLOW]
    return {"agents": agent_items, "skills": skill_items, "workflow": {"id": workflow["id"], "type": "Workflow", "name": workflow["name"], "purpose": workflow["purpose"]}, "counts": {"agents": 4, "skills": 2, "workflows": 1}}


def list_artifacts(project_id: str) -> list[dict[str, Any]]:
    project = runtime().projects.resolve(project_id)
    items: list[dict[str, Any]] = []
    roots = [project["path"] / ".workbench" / "agent-runs", project["path"] / "artifacts"]
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*"), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
            if path.is_file() and not path.name.startswith("."):
                items.append({"path": path.relative_to(project["path"]).as_posix(), "name": path.name, "bytes": path.stat().st_size, "updated_at": int(path.stat().st_mtime)})
            if len(items) >= 200:
                return items
    return items


class Handler(SimpleHTTPRequestHandler):
    server_version = "PMWorkbench/2.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 25_000_000:
            raise ContractError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ContractError("请求体必须是 JSON 对象")
        return value

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path in {"/", "/pm-workbench.html", "/cockpit.html"}:
                body = HTML_FILE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/projects":
                self.send_json({"projects": [project_summary(project) for project in runtime().projects.discover().values()]})
                return
            if parsed.path == "/api/project":
                self.send_json(project_summary(runtime().projects.resolve(project_id_from(self))))
                return
            if parsed.path == "/api/project/overview":
                self.send_json(project_overview(project_id_from(self)))
                return
            if parsed.path == "/api/project/intake":
                self.send_json(intake_document(runtime().projects.resolve(project_id_from(self))))
                return
            if parsed.path == "/api/ai/status":
                self.send_json(gateway_status())
                return
            if parsed.path == "/api/catalog":
                self.send_json(catalog())
                return
            if parsed.path == "/api/agents/tasks":
                project_id = project_id_from(self)
                tasks = runtime().store.list(project_id=project_id)
                self.send_json({"tasks": tasks})
                return
            if parsed.path == "/api/agents/task":
                self.send_json(task_details((query.get("id") or [""])[0]))
                return
            if parsed.path == "/api/workflows":
                project_id = project_id_from(self)
                self.send_json({"runs": WorkflowScheduler(runtime(), available_tools()).list(project_id)})
                return
            if parsed.path == "/api/workflows/run":
                run_id = (query.get("id") or [""])[0]
                self.send_json(WorkflowScheduler(runtime(), available_tools()).get(run_id))
                return
            if parsed.path == "/api/artifacts":
                self.send_json({"artifacts": list_artifacts(project_id_from(self))})
                return
            self.send_error(404)
        except (ContractError, StateTransitionError, ValueError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            data = self.read_json()
            if parsed.path == "/api/projects":
                self.send_json({"ok": True, "project": create_project(data)}, 201)
                return
            if parsed.path == "/api/agents/start":
                project_id = project_id_from(self, data)
                package_id = str(data.get("agent_id") or "")
                package = runtime().registry.packages.get(package_id)
                if not package:
                    raise ContractError("未知公开 Agent")
                mode_id = str(data.get("mode") or package["modes"][0]["id"])
                mode = next((item for item in package["modes"] if item["id"] == mode_id), None)
                if not mode:
                    raise ContractError("Agent 模式无效")
                if mode.get("approval_required") and data.get("pm_confirmed") is not True:
                    raise ContractError("正式 PRD、设计任务或概念 Demo 需要先勾选 PM 已确认产品方案")
                materials = data.get("source_artifacts") or []
                goal = str(data.get("goal") or "").strip()
                decision = str(data.get("decision_to_support") or "").strip()
                if not goal or not decision:
                    raise ContractError("任务内容和要支持的决定不能为空")
                allowed = [tool for tool in runtime().registry.agents[package["runtime_agent_id"]]["allowed_tools"] if tool in available_tools()]
                task, _ = runtime().create_task(
                    project_id=project_id, agent_id=package["runtime_agent_id"], task_type=mode["task_type"],
                    goal=goal, decision_to_support=decision, source_artifacts=materials,
                    allowed_tools=allowed, authority_level="draft_write",
                    idempotency_key=str(data.get("idempotency_key") or ""),
                )
                spawn(run_task, task["id"])
                self.send_json({"ok": True, "task": task}, 201)
                return
            if parsed.path == "/api/agents/update":
                task_id = str(data.get("task_id") or "")
                action = str(data.get("action") or "")
                if action == "provide_input":
                    runtime().store.provide_input(str(data.get("input_id") or ""), data.get("responses") or {}, "pm")
                    spawn(run_task, task_id)
                elif action == "decide_approval":
                    approved = bool(data.get("approved"))
                    runtime().store.decide_approval(str(data.get("approval_id") or ""), approved, "pm", str(data.get("note") or ""))
                    if approved:
                        spawn(run_task, task_id)
                elif action == "retry":
                    task = runtime().store.get(task_id)
                    runtime().store.transition(task_id, "queued", "pm", reason="PM 手动重试")
                    spawn(run_task, task["id"])
                else:
                    raise ContractError("Agent 更新动作无效")
                self.send_json({"ok": True, "task": task_details(task_id)})
                return
            if parsed.path == "/api/workflows/start":
                project_id = project_id_from(self, data)
                scheduler = WorkflowScheduler(runtime(), available_tools())
                run = scheduler.start(project_id, CORE_WORKFLOW, str(data.get("goal") or ""), str(data.get("decision_to_support") or ""))
                spawn(run_workflow, run["id"])
                self.send_json({"ok": True, "run": run}, 201)
                return
            if parsed.path == "/api/workflows/update":
                run_id = str(data.get("run_id") or "")
                action = str(data.get("action") or "")
                scheduler = WorkflowScheduler(runtime(), available_tools())
                if action == "decide":
                    run = scheduler.decide(run_id, str(data.get("approval_id") or ""), bool(data.get("approved")), "pm", str(data.get("note") or ""))
                    spawn(run_workflow, run_id)
                elif action == "resume":
                    run = scheduler.resume(run_id)
                    spawn(run_workflow, run_id)
                elif action == "cancel":
                    run = scheduler.cancel(run_id)
                else:
                    raise ContractError("Workflow 更新动作无效")
                self.send_json({"ok": True, "run": run})
                return
            if parsed.path == "/api/materials/upload":
                project_id = project_id_from(self, data)
                project = runtime().projects.resolve(project_id)
                name = normalize_upload_name(data.get("name") or "material.txt")
                supersedes_id = str(data.get("supersedes_id") or "").strip()
                previous = None
                previous_document = None
                previous_index = -1
                if supersedes_id:
                    previous_document, previous, previous_index = find_import_item(project, supersedes_id)
                    if not material_is_active(previous):
                        raise ContractError("待替换资料已经不在当前资料范围内")
                content = base64.b64decode(str(data.get("content_base64") or ""), validate=True)
                if not content or len(content) > 20_000_000:
                    raise ContractError("材料为空或超过 20MB")
                target = project["path"] / ".workbench" / "uploads" / f"{uuid.uuid4().hex[:8]}-{name}"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                relative = target.relative_to(project["path"]).as_posix()
                imported = record_import(project, {
                    "kind": str(data.get("source_kind") or "local_file"),
                    "status": "已导入",
                    "name": name,
                    "path": relative,
                    "original_path": str(data.get("relative_path") or name),
                    "bytes": len(content),
                    "material_version": data.get("material_version") or project_version(project),
                })
                if supersedes_id and previous is not None and previous_document is not None:
                    previous["status"] = "已被替换"
                    previous["replaced_by"] = imported["id"]
                    previous_document["items"][previous_index] = previous
                    write_imports(project, previous_document)
                mark_intake_stale(project, f"资料“{name}”已上传")
                self.send_json({"ok": True, "path": relative, "original_path": str(data.get("relative_path") or name), "item": imported}, 201)
                return
            if parsed.path == "/api/materials/update":
                project_id = project_id_from(self, data)
                project = runtime().projects.resolve(project_id)
                self.send_json({"ok": True, "item": update_import_item(project, data)})
                return
            if parsed.path == "/api/project/intake":
                project_id = project_id_from(self, data)
                project = runtime().projects.resolve(project_id)
                action = str(data.get("action") or "analyze")
                document = intake_document(project)
                if action == "analyze":
                    document = analyze_project_intake(project_id, data.get("material_version"))
                elif action == "save_note":
                    note = str(data.get("note") or "").strip()
                    if not note:
                        raise ContractError("PM 补充说明不能为空")
                    notes = document.get("pm_notes") if isinstance(document.get("pm_notes"), list) else []
                    notes.append({"text": note, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
                    document["pm_notes"] = notes[-50:]
                    document["status"] = "needs_analysis"
                    document["draft_stale"] = True
                    document["stale_reason"] = "PM 补充说明已更新"
                    intake_path(project).parent.mkdir(parents=True, exist_ok=True)
                    intake_path(project).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                elif action == "save_draft":
                    analysis = str(data.get("analysis") or "").strip()
                    if not analysis:
                        raise ContractError("AI 草稿不能为空")
                    document["analysis"] = analysis[:100000]
                    document["status"] = "draft"
                    document["edited_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    intake_path(project).parent.mkdir(parents=True, exist_ok=True)
                    intake_path(project).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                elif action == "reject":
                    reason = str(data.get("reason") or "").strip()
                    if not reason:
                        raise ContractError("请填写驳回原因")
                    if not str(document.get("analysis") or "").strip():
                        raise ContractError("还没有项目分析草稿")
                    document["status"] = "rejected"
                    document["rejection_reason"] = reason[:1000]
                    document["rejected_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    intake_path(project).parent.mkdir(parents=True, exist_ok=True)
                    intake_path(project).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                elif action == "confirm":
                    if not str(document.get("analysis") or "").strip():
                        raise ContractError("还没有项目分析草稿")
                    if document.get("draft_stale"):
                        raise ContractError("资料或 PM 说明已变化，请先重新分析当前资料版本")
                    document["status"] = "confirmed"
                    document["confirmed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    document["confirmed_analysis"] = document.get("analysis", "")
                    document["confirmed_version"] = document.get("analysis_version", project_version(project))
                    document["draft_stale"] = False
                    document["stale_reason"] = ""
                    document["rejection_reason"] = ""
                    intake_path(project).parent.mkdir(parents=True, exist_ok=True)
                    intake_path(project).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                else:
                    raise ContractError("项目资料动作只能是 analyze、save_note 或 confirm")
                self.send_json({"ok": True, "intake": document})
                return
            if parsed.path == "/api/project/import":
                project_id = project_id_from(self, data)
                project = runtime().projects.resolve(project_id)
                raw_sources = data.get("sources") or []
                if not isinstance(raw_sources, list):
                    raise ContractError("sources 必须是数组")
                saved = []
                for raw in raw_sources[:30]:
                    url = str(raw.get("url") if isinstance(raw, dict) else raw).strip()
                    if not re.fullmatch(r"https?://[^\s]+", url):
                        raise ContractError("来源链接必须是 http(s) URL")
                    kind, status = classify_source_url(url)
                    saved.append(record_import(project, {"kind": kind, "status": status, "name": url, "url": url, "material_version": data.get("material_version") or project_version(project)}))
                mark_intake_stale(project, "外部来源已更新")
                self.send_json({"ok": True, "sources": saved, "overview": project_overview(project_id)}, 201)
                return
            self.send_error(404)
        except (ContractError, StateTransitionError, ValueError, json.JSONDecodeError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 PM AI 工作台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()
    runtime()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"PM AI 工作台已启动：http://{args.host}:{args.port}/pm-workbench.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

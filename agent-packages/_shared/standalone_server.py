#!/usr/bin/env python3
"""独立 Agent 浏览器入口，复用工作台同一 AgentRuntime / AgentWorker。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

try:
    from gateway_client import GatewayError, chat_completion, post_json
except ImportError:
    _root_scripts = Path(__file__).resolve().parents[2] / "scripts"
    _local_scripts = Path(__file__).resolve().parent
    sys.path.insert(0, str(_root_scripts if (_root_scripts / "gateway_client.py").is_file() else _local_scripts))
    from gateway_client import GatewayError, chat_completion, post_json


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def keychain_token() -> str:
    token = os.environ.get("PM_WORKBENCH_API_KEY", "").strip()
    if token:
        return token
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "pm-workbench-ai-gateway", "-a", "default", "-w"],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    auth = load_json(Path.home() / ".codex" / "auth.json", {})
    return str(auth.get("OPENAI_API_KEY") or "").strip() if isinstance(auth, dict) else ""


def gateway_config() -> dict[str, Any]:
    value = {"base_url": "https://aigateway-infra.oppaya.app", "model": "gpt-5.6-sol", "reasoning_effort": "high", "allow_fixed_gateway_tls_exception": True}
    local = load_json(Path.home() / ".config" / "pm-workbench" / "gateway.json", {})
    if isinstance(local, dict):
        value.update(local)
    return value


def gateway_model(system: str, messages: list[dict[str, str]], max_tokens: int) -> str:
    config = gateway_config()
    token = keychain_token()
    if not token:
        raise RuntimeError("未找到可用网关凭据，请运行 setup.command 或登录 Codex")
    base = str(config.get("base_url") or config.get("baseUrl") or "").rstrip("/")
    try:
        return chat_completion(
            base_url=base,
            model=str(config.get("model") or "gpt-5.6-sol"),
            reasoning_effort=str(config.get("reasoning_effort") or config.get("reasoningEffort") or "high"),
            token=token,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            allow_fixed_gateway_tls_exception=bool(config.get("allow_fixed_gateway_tls_exception", True)),
        )
    except GatewayError as exc:
        raise RuntimeError(str(exc)) from exc


def tavily_key() -> str:
    value = os.environ.get("TAVILY_API_KEY", "").strip()
    if value:
        return value
    path = Path.home() / ".config" / "pm-workbench" / "tavily-api-key"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def web_research(_task: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    key = tavily_key()
    if not key:
        raise RuntimeError("公开网页研究未配置 Tavily")
    action = str(arguments.get("action") or "search")
    if action == "search":
        query = str(arguments.get("query") or "").strip()
        endpoint = "search"
        payload = {"api_key":key,"query":query,"max_results":min(max(int(arguments.get("max_results") or 6),1),8),"search_depth":"advanced"}
    elif action == "extract":
        url = str(arguments.get("url") or "").strip()
        endpoint = "extract"
        payload = {"api_key":key,"urls":[url],"extract_depth":"advanced"}
    else:
        raise ValueError(f"web_research 不支持 action: {action}")
    value = post_json("https://api.tavily.com/" + endpoint, payload, timeout_seconds=60)
    return {"action":action,"results":value.get("results") or []}


def ensure_project(path: Path, package: dict[str, Any]) -> str:
    path.mkdir(parents=True, exist_ok=True)
    project_id = re.sub(r"[^a-z0-9-]+", "-", path.name.lower()).strip("-") or "pm-agent-project"
    project_id = (project_id[:36] or "pm-agent-project")
    files = {
        "HOME.md": f"# {path.name}\n\n这是独立 Agent 的项目入口。请在运行表单中补充目标用户、问题、材料和要支持的决定。\n",
        "PROJECT-CONTEXT.md": "# 项目上下文\n\n## 产品是什么\n\n待补充。\n\n## 给谁使用\n\n待补充。\n\n## 当前要解决什么\n\n待补充。\n",
        "project.yaml": f'schema_version: "2.0"\nproject: "{project_id}"\nstage: discovery\nversion: v0.1\nobjective: ""\nactive_bet: ""\nactive_feature: ""\n',
        "manifest.yaml": f'name: "{path.name}"\nstatus: discovery\nworkflow: ""\nversion: v0.1\n',
        "memory/canon.md": "# 已确认事实\n",
        "memory/assumptions.md": "# 待验证假设\n",
        "memory/evidence.md": "# 证据\n",
        "memory/decisions/README.md": "# PM 决定\n",
    }
    for relative, content in files.items():
        target = path / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    config_path = path / "agent-config.json"
    config = load_json(config_path, {})
    runtime_id = package["runtime_agent_id"]
    # 独立 Package 只拥有自己的 Agent，不能继承完整工作台的 Agent 配置。
    config["enabled_agents"] = [runtime_id]
    config.setdefault("schema_version", "2.0")
    config.setdefault("project_id", project_id)
    config.setdefault("domain_packs", [])
    config.setdefault("workflow_allowlist", [])
    config.setdefault("authority_ceiling", "draft_write")
    if not isinstance(config.get("tool_overrides"), dict):
        config["tool_overrides"] = {}
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return project_id


def load_engine(package_dir: Path, project_dir: Path):
    workbench_root = package_dir.parents[1] if (package_dir.parents[1] / "scripts" / "agent_runtime.py").is_file() else package_dir
    engine_dir = workbench_root / "scripts" if (workbench_root / "scripts" / "agent_runtime.py").is_file() else workbench_root / "runtime"
    os.environ["PM_AGENT_PROJECT_DIR"] = str(project_dir)
    if workbench_root == package_dir:
        manifest = load_json(package_dir / "agent-package.json", {})
        os.environ["PM_AGENT_ONLY"] = str(manifest.get("id") or package_dir.name)
    sys.path.insert(0, str(engine_dir))
    from agent_runtime import AgentRuntime, AgentWorker, ToolExecutor
    return workbench_root, AgentRuntime, AgentWorker, ToolExecutor


class Runner:
    def __init__(self, package_dir: Path, project_dir: Path):
        self.package_dir = package_dir.resolve()
        self.project_dir = project_dir.resolve()
        self.package = load_json(self.package_dir / "agent-package.json", {})
        self.project_id = ensure_project(self.project_dir, self.package)
        self.root, AgentRuntime, AgentWorker, ToolExecutor = load_engine(self.package_dir, self.project_dir)
        self.runtime = AgentRuntime(self.root, self.project_dir / ".pm-agent" / "agent-runtime.db")
        self.AgentWorker = AgentWorker
        self.ToolExecutor = ToolExecutor
        local_assets = self.package_dir / "assets"
        self.assets_dir = local_assets if (local_assets / "standalone.html").is_file() else self.package_dir.parent / "_shared"

    def memory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.memory_action(self.project_id, str(arguments.get("action") or "context"), arguments)

    def tool_handlers(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if tavily_key():
            result["web_research"] = web_research
            if (self.package_dir / "scripts" / "social_ingest.py").is_file():
                def social(_task: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
                    source=str(arguments.get("source") or "reddit");query=str(arguments.get("query") or "").strip();limit=min(max(int(arguments.get("limit") or 8),1),20)
                    command=[sys.executable,str(self.package_dir/"scripts"/"social_ingest.py")];timeout=90;boundary="只读取公开 Reddit 或用户主动导出的材料"
                    target=str(arguments.get("path") or "").strip()
                    if source == "reddit": command += ["reddit",query,"--limit",str(limit)]
                    elif source == "xiaohongshu" and not target:
                        if not query: raise RuntimeError("小红书 live 抓取需要 query 关键词")
                        command += ["xhs-live",query,"--limit",str(limit)];timeout=260;boundary="小红书 live 抓取：使用你已扫码登录的会话，仅个人研究用途、账号风险自负；会话失效会提示重新登录"
                    elif source == "weibo" and not target:
                        if not query: raise RuntimeError("微博 live 抓取需要 query 关键词")
                        command += ["wb-live",query,"--limit",str(limit)];timeout=260;boundary="微博 live 抓取：使用你已扫码登录的会话，仅个人研究用途、账号风险自负；会话失效会提示重新登录"
                    elif source == "x" and not target:
                        if not query: raise RuntimeError("X live 抓取需要 query 关键词")
                        command += ["x-live",query,"--limit",str(limit)];timeout=180;boundary="X live 抓取：使用你配置的 twscrape 账号，仅个人研究用途、账号风险自负；未配置或登录失效会提示 x-login"
                    elif source in {"x","xiaohongshu","mediacrawler"}:
                        allowed=set(_task.get("source_artifacts") or [])
                        if not target or target not in allowed: raise RuntimeError("X、或用导出文件方式的小红书，必须先在 source_artifacts 里授权该 JSON")
                        path=Path(target)
                        if not path.is_absolute(): path=(self.project_dir / target.removeprefix(f"projects/{self.project_dir.name}/")).resolve()
                        if not path.is_file() or path.suffix.lower() != ".json": raise RuntimeError("社媒导入文件必须是 JSON")
                        command += ["x" if source == "x" else "mediacrawler",str(path)]
                    else: raise RuntimeError("source 只能是 reddit、x、xiaohongshu 或 weibo")
                    completed=subprocess.run(command,capture_output=True,text=True,timeout=timeout,check=False)
                    if completed.returncode!=0:raise RuntimeError(completed.stderr.strip() or "社媒采集失败")
                    return {"source":source,"query":query,"posts":json.loads(completed.stdout),"login_boundary":boundary}
                result["social_ingest"] = social
        demo_script = self.package_dir / "scripts" / "demo_gen.py"
        if demo_script.is_file() and keychain_token():
            def demo_html(_task: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
                spec = str(arguments.get("spec") or arguments.get("brief") or "").strip()
                if not spec:
                    raise RuntimeError("demo_html.spec 不能为空")
                out_dir = self.project_dir / ".workbench" / "demos"
                out_dir.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256(spec.encode("utf-8")).hexdigest()[:16]
                out_file = out_dir / f"{digest}.html"
                env = dict(os.environ, PM_WORKBENCH_API_KEY=keychain_token())
                completed = subprocess.run(
                    [sys.executable, str(demo_script), spec, str(out_file)],
                    capture_output=True, text=True, timeout=290, check=False, env=env,
                )
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip() or "demo 生成失败")
                try:
                    generated = json.loads(completed.stdout.strip().splitlines()[-1])
                except (ValueError, IndexError):
                    generated = {"ok": out_file.is_file(), "artifact": str(out_file)}
                if not out_file.is_file() or out_file.stat().st_size < 500 or not generated.get("ok"):
                    detail = str(generated.get("error") or generated.get("message") or "网关没有返回有效 HTML")
                    raise RuntimeError(f"demo 生成未完成：{detail}")
                generated["path"] = str(out_file)
                generated["label"] = "concept_validation"
                return generated
            result["demo_html"] = demo_html
        persona_script = self.package_dir / "scripts" / "ux_review.py"
        if persona_script.is_file() and keychain_token():
            def persona_review(_task: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
                target = str(arguments.get("target") or "").strip()
                persona = str(arguments.get("persona") or "团粉").strip()
                if not target:
                    raise RuntimeError("persona_review.target 不能为空")
                allowed = set(_task.get("source_artifacts") or [])
                if target not in allowed:
                    raise RuntimeError("persona_review 只能读取任务已授权材料")
                target_path = Path(target)
                if not target_path.is_absolute():
                    project_prefix = f"projects/{self.project_dir.name}/"
                    normalized = target[len(project_prefix):] if target.startswith(project_prefix) else target
                    target_path = (self.project_dir / normalized).resolve()
                if not target_path.is_file() or target_path.suffix.lower() not in {".html", ".htm"}:
                    raise RuntimeError("persona_review.target 必须是已授权 HTML 文件")
                env = dict(os.environ, PM_WORKBENCH_API_KEY=keychain_token())
                completed = subprocess.run(
                    [sys.executable, str(persona_script), str(target_path), persona],
                    capture_output=True, text=True, timeout=260, check=False, env=env,
                )
                if completed.returncode != 0:
                    raise RuntimeError(completed.stderr.strip() or "persona review 失败")
                return {"ok": True, "status": "completed", "persona": persona, "target": target, "review": completed.stdout.strip()}
            result["persona_review"] = persona_review
        bridge = self.root / "runtime" / "connectors" / "critic_mcp_bridge.py"
        codex_config = Path.home() / ".codex" / "config.toml"
        gateway_ready = codex_config.is_file() and "[mcp_servers.critic_gateway]" in codex_config.read_text(encoding="utf-8", errors="ignore")
        if bridge.is_file() and gateway_ready:
            def data(_task: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
                config=load_json(self.project_dir/"agent-config.json",{});binding=str((config.get("tool_overrides",{}).get("data_gateway") or {}).get("binding") or "")
                action=str(arguments.get("action") or "query").strip()
                if action not in {"list_projects", "bind_project", "query"}:raise RuntimeError("data_gateway.action 只能是 list_projects、bind_project 或 query")
                requested_binding=str(arguments.get("project_code") or "").strip()
                if requested_binding:binding=requested_binding
                sql=str(arguments.get("sql") or "").strip()
                if action in {"bind_project", "query"} and not binding:raise RuntimeError("当前项目未配置 data_gateway binding；请先用 list_projects 查看可用数据项目，再请 PM 明确选择 project_code")
                if action == "query" and (not re.match(r"(?is)^\s*(select|with)\b",sql) or re.search(r"(?is)\b(insert|update|delete|drop|alter|create|truncate)\b",sql)):raise RuntimeError("data_gateway 只允许只读查询")
                command=[sys.executable,str(bridge),"--action",action]
                if action in {"bind_project", "query"}: command += ["--project",binding,"--sql",sql]
                completed=subprocess.run(command,capture_output=True,text=True,timeout=300,check=False)
                value=json.loads(completed.stdout)
                if completed.returncode!=0 or not value.get("ok"):raise RuntimeError(str(value.get("error") or "data_gateway 失败"))
                return value
            result["data_gateway"] = data
        return result

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        mode_id = str(payload.get("mode") or self.package["modes"][0]["id"])
        mode = next((item for item in self.package["modes"] if item["id"] == mode_id), None)
        if not mode:
            raise ValueError("运行模式无效")
        inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
        decision = str(inputs.get("decision") or inputs.get("decision_to_support") or "").strip()
        if not decision:
            decision = "判断当前材料是否足以支持下一步，并给出明确行动"
        goal = "\n".join(f"{key}: {value}" for key, value in inputs.items() if str(value).strip())
        if not goal:
            raise ValueError("请至少填写一项任务信息")
        local_tools = {"project_memory", "artifact_store", "signal_ledger", "material_inspector", "browser_review", "finding_ledger", "demo_builder"}
        active_handlers = self.tool_handlers()
        allowed = [tool for tool in self.package["runtime"]["allowed_tools"] if tool in local_tools or tool in active_handlers]
        task, _ = self.runtime.create_task(
            project_id=self.project_id, agent_id=self.package["runtime_agent_id"], task_type=mode["task_type"],
            goal=goal, decision_to_support=decision, source_artifacts=payload.get("material_paths") or [],
            allowed_tools=allowed, authority_level="draft_write",
            memory_source=str(payload.get("source") or "standalone"),
            memory_session_id=str(payload.get("session_id") or ""),
        )
        worker = self.AgentWorker(self.runtime, gateway_model, self.ToolExecutor(self.runtime, active_handlers))
        worker.run_with_retries(task["id"], "standalone-worker")
        return self.details(task["id"])

    def details(self, task_id: str) -> dict[str, Any]:
        task = self.runtime.store.get(task_id)
        task["events"] = self.runtime.store.events(task_id)
        task["input_requests"] = self.runtime.store.input_requests(task_id)
        task["approvals"] = self.runtime.store.approvals(task_id)
        return task

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("task_id") or "")
        action = str(payload.get("action") or "")
        if action == "provide_input":
            self.runtime.store.provide_input(str(payload.get("input_id") or ""), payload.get("responses") or {}, "pm")
        elif action == "decide_approval":
            approved = bool(payload.get("approved"))
            self.runtime.store.decide_approval(str(payload.get("approval_id") or ""), approved, "pm")
            if not approved:
                return self.details(task_id)
        else:
            raise ValueError("更新动作无效")
        worker = self.AgentWorker(self.runtime, gateway_model, self.ToolExecutor(self.runtime, self.tool_handlers()))
        worker.run_with_retries(task_id, "standalone-worker")
        return self.details(task_id)


def handler_factory(runner: Runner):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, directory=str(runner.assets_dir), **kwargs)
        def log_message(self, format: str, *args: Any) -> None:
            return
        def json_response(self, value: Any, status: int = 200) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status);self.send_header("Content-Type", "application/json; charset=utf-8");self.send_header("Content-Length", str(len(body)));self.send_header("Cache-Control", "no-store");self.end_headers();self.wfile.write(body)
        def do_GET(self) -> None:
            if self.path == "/api/package":
                config = gateway_config();self.json_response({"ok":True,"package":runner.package,"project":str(runner.project_dir),"gateway":{"configured":bool(keychain_token()),"model":config["model"],"reasoning_effort":config["reasoning_effort"]}});return
            if self.path.startswith("/api/task?"):
                task_id = self.path.split("id=", 1)[-1];self.json_response({"ok":True,"task":runner.details(task_id)});return
            if self.path in {"/", "/index.html"}:self.path="/standalone.html"
            super().do_GET()
        def do_POST(self) -> None:
            try:
                length=int(self.headers.get("Content-Length") or 0);payload=json.loads(self.rfile.read(length).decode("utf-8"))
                if self.path=="/api/run":task=runner.start(payload)
                elif self.path=="/api/update":task=runner.update(payload)
                else:raise ValueError("未知接口")
                self.json_response({"ok":True,"task":task},201)
            except Exception as exc:self.json_response({"ok":False,"error":str(exc)},400)
    return Handler


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("--package-dir",type=Path,required=True);parser.add_argument("--project",type=Path,default=Path.cwd());parser.add_argument("--port",type=int,default=0);parser.add_argument("--check",action="store_true");parser.add_argument("--no-open",action="store_true");args=parser.parse_args()
    runner=Runner(args.package_dir,args.project)
    if args.check:print(json.dumps({"ok":True,"package":runner.package["id"],"engine":"AgentWorker","project":str(runner.project_dir)},ensure_ascii=False));return
    server=ThreadingHTTPServer(("127.0.0.1",args.port),handler_factory(runner));url=f"http://127.0.0.1:{server.server_port}/";print(url,flush=True)
    if not args.no_open:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=="__main__":main()

#!/usr/bin/env python3
"""PM 工作台统一网关客户端。

当前公司网关对 Python urllib 请求会返回 403，curl 请求可正常工作。
Token 通过 curl config 临时文件传入，避免出现在进程参数和日志中。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - macOS/Linux provide fcntl
    fcntl = None


class GatewayError(RuntimeError):
    def __init__(self, message: str, *, category: str, status_code: int | None = None):
        super().__init__(message)
        self.category = category
        self.status_code = status_code


DEFAULT_GATEWAY_CONFIG = {
    "base_url": "https://aigateway-infra.oppaya.app",
    "model": "gpt-5.6-sol",
    "reasoning_effort": "high",
    "allow_fixed_gateway_tls_exception": True,
}


def local_gateway_config() -> dict[str, Any]:
    """读取本机网关偏好；绝不从项目文件或浏览器读取 Token。"""
    path = Path.home() / ".config" / "pm-workbench" / "gateway.json"
    config = dict(DEFAULT_GATEWAY_CONFIG)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            for key in DEFAULT_GATEWAY_CONFIG:
                if value.get(key) not in (None, ""):
                    config[key] = value[key]
    except (OSError, json.JSONDecodeError):
        pass
    return config


def read_local_token() -> str:
    """按本机优先级读取凭据，供独立脚本复用且不把凭据写入参数。"""
    for name in ("PM_WORKBENCH_API_KEY", "AIGW_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    security = shutil.which("security")
    if security:
        try:
            completed = subprocess.run(
                [security, "find-generic-password", "-s", "pm-workbench-ai-gateway", "-a", "default", "-w"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                return completed.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return ""


@contextmanager
def _gateway_process_lock():
    """跨工作台、独立版和 MCP 进程串行化模型请求。"""
    if fcntl is None:
        yield
        return
    lock_dir = Path.home() / ".config" / "pm-workbench"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "gateway-request.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _response_detail(raw: str) -> str:
    text = raw.strip()
    if not text:
        return "网关没有返回错误详情"
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            error = value.get("error")
            if isinstance(error, dict):
                text = str(error.get("message") or error.get("code") or error)
            else:
                text = str(value.get("message") or value)
    except json.JSONDecodeError:
        pass
    return re.sub(r"\s+", " ", text)[:500]


def _category(status_code: int | None) -> str:
    if status_code in {401, 403}:
        return "gateway_auth"
    if status_code in {408, 409, 429}:
        return "gateway_rate_limit"
    if status_code is not None and status_code >= 500:
        return "gateway_upstream"
    return "gateway_transport"


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 60,
    insecure: bool = False,
) -> dict[str, Any]:
    """通过 curl 发 JSON POST，供网关和公开研究接口共用。"""
    curl = shutil.which("curl")
    if not curl:
        raise GatewayError("当前系统未找到 curl", category="curl_missing")
    with tempfile.TemporaryDirectory(prefix="pm-workbench-http-") as directory:
        directory_path = Path(directory)
        body_path = directory_path / "request.json"
        config_path = directory_path / "curl.conf"
        body_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        config_lines = [
            f"url = {json.dumps(url)}",
            f"header = {json.dumps('Content-Type: application/json')}",
            f"header = {json.dumps('User-Agent: curl/8.4.0')}",
            f"data-binary = {json.dumps('@' + str(body_path))}",
            f"max-time = {int(timeout_seconds)}",
            f"write-out = {json.dumps(chr(10) + '__PM_HTTP_STATUS__:%{http_code}' + chr(10))}",
        ]
        for key, value in (headers or {}).items():
            config_lines.append(f"header = {json.dumps(f'{key}: {value}')}")
        if insecure:
            config_lines.append("insecure")
        config_path.write_text("\n".join(config_lines) + "\n", encoding="utf-8")
        completed = subprocess.run(
            [curl, "--silent", "--show-error", "--fail-with-body", "--config", str(config_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 10,
            check=False,
            env={**os.environ, "CURL_HOME": str(directory_path)},
        )
    match = re.search(r"\n__PM_HTTP_STATUS__:(\d+)\s*$", completed.stdout or "")
    status_code = int(match.group(1)) if match else None
    raw_body = (completed.stdout or "")[: match.start()] if match else completed.stdout or ""
    if completed.returncode != 0:
        detail = _response_detail(raw_body or completed.stderr)
        suffix = f"（HTTP {status_code}）" if status_code else ""
        raise GatewayError(f"HTTP 请求失败{suffix}：{detail}", category=_category(status_code), status_code=status_code)
    try:
        value = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise GatewayError("HTTP 接口返回了无法解析的 JSON", category="gateway_protocol") from exc
    if not isinstance(value, dict):
        raise GatewayError("HTTP 接口返回格式不是对象", category="gateway_protocol")
    return value


def post_stream(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 180,
    insecure: bool = False,
) -> str:
    """通过 curl 接收 SSE；同时兼容网关意外返回普通 JSON 的情况。"""
    curl = shutil.which("curl")
    if not curl:
        raise GatewayError("当前系统未找到 curl", category="curl_missing")
    with tempfile.TemporaryDirectory(prefix="pm-workbench-stream-") as directory:
        directory_path = Path(directory)
        body_path = directory_path / "request.json"
        config_path = directory_path / "curl.conf"
        body_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        config_lines = [
            f"url = {json.dumps(url)}",
            f"header = {json.dumps('Content-Type: application/json')}",
            f"header = {json.dumps('Accept: text/event-stream, application/json')}",
            f"header = {json.dumps('User-Agent: curl/8.4.0')}",
            f"data-binary = {json.dumps('@' + str(body_path))}",
            f"max-time = {int(timeout_seconds)}",
            f"write-out = {json.dumps(chr(10) + '__PM_HTTP_STATUS__:%{http_code}' + chr(10))}",
        ]
        for key, value in (headers or {}).items():
            config_lines.append(f"header = {json.dumps(f'{key}: {value}')}")
        if insecure:
            config_lines.append("insecure")
        config_path.write_text("\n".join(config_lines) + "\n", encoding="utf-8")
        completed = subprocess.run(
            [curl, "--silent", "--show-error", "--fail-with-body", "--no-buffer", "--config", str(config_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 10,
            check=False,
            env={**os.environ, "CURL_HOME": str(directory_path)},
        )
    match = re.search(r"\n__PM_HTTP_STATUS__:(\d+)\s*$", completed.stdout or "")
    status_code = int(match.group(1)) if match else None
    raw_body = (completed.stdout or "")[: match.start()] if match else completed.stdout or ""
    if completed.returncode != 0:
        detail = _response_detail(raw_body or completed.stderr)
        suffix = f"（HTTP {status_code}）" if status_code else ""
        raise GatewayError(f"HTTP 请求失败{suffix}：{detail}", category=_category(status_code), status_code=status_code)
    return raw_body


def _stream_content(raw_body: str) -> str:
    """解析 OpenAI SSE delta；网关返回普通 JSON 时直接读取 message.content。"""
    chunks: list[str] = []
    json_candidates: list[str] = []
    for line in raw_body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            continue
        json_candidates.append(line)
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        choices = value.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}
        content: Any = delta.get("content") if isinstance(delta, dict) else None
        if content is None:
            content = (choice.get("message") or {}).get("content")
        if isinstance(content, list):
            content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
        if isinstance(content, str):
            chunks.append(content)
    if chunks:
        return "".join(chunks)
    try:
        value = json.loads(raw_body.strip())
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict):
        choices = value.get("choices") or []
        if choices:
            content = ((choices[0].get("message") or {}).get("content") if isinstance(choices[0], dict) else None)
            if isinstance(content, str):
                return content
    return ""


def chat_completion(
    *,
    base_url: str,
    model: str,
    reasoning_effort: str,
    token: str,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    allow_fixed_gateway_tls_exception: bool = True,
    timeout_seconds: int = 180,
    stream: bool = True,
) -> str:
    if not token:
        raise GatewayError("未找到可用网关凭据", category="credential_missing")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "reasoning_effort": reasoning_effort,
        "max_completion_tokens": max_tokens,
        "stream": bool(stream),
    }
    endpoint = base_url.rstrip("/") + "/v1/chat/completions"
    fixed_gateway = "aigateway-infra.oppaya.app" in endpoint
    with _gateway_process_lock():
        if stream:
            raw_body = post_stream(
                endpoint,
                payload,
                headers={"Authorization": "Bearer " + token},
                timeout_seconds=timeout_seconds,
                insecure=fixed_gateway and allow_fixed_gateway_tls_exception,
            )
            content = _stream_content(raw_body)
        else:
            value = post_json(
                endpoint,
                payload,
                headers={"Authorization": "Bearer " + token},
                timeout_seconds=timeout_seconds,
                insecure=fixed_gateway and allow_fixed_gateway_tls_exception,
            )
            try:
                value = dict(value)
            except (TypeError, ValueError) as exc:
                raise GatewayError("AI 网关返回格式无效", category="gateway_protocol") from exc
            choices = value.get("choices") or []
            content = ((choices[0].get("message") or {}).get("content") if choices else None)
            if isinstance(content, list):
                content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    if not isinstance(content, str) or not content.strip():
        raise GatewayError("AI 网关返回了空内容", category="gateway_protocol")
    return content

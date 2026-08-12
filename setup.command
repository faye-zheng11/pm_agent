#!/bin/zsh
set -euo pipefail

WORKBENCH_ROOT="${0:A:h}"
CONFIG_DIR="$HOME/.config/pm-workbench"
MARKETPLACE_DIR="$WORKBENCH_ROOT"
PLUGIN_DIR="$MARKETPLACE_DIR/.agents/plugins/plugins"
SKILL_DIR="$HOME/.codex/skills"
RUNTIME_DIR="$CONFIG_DIR/runtime"
BROWSER_VENV="$RUNTIME_DIR/browser-venv"
SECRET_FILE="$WORKBENCH_ROOT/bootstrap/internal-gateway.key"
CODEX_AUTH_FILE="$HOME/.codex/auth.json"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "当前交付版仅支持 macOS。"
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 Python 3，请先安装 Python 3.11 或更高版本。"
  exit 1
fi
PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "当前 Python 版本为 $PYTHON_VERSION，需要 Python 3.11 或更高版本。"
  exit 1
fi
if [[ ! -s "$SECRET_FILE" && ! -s "$CODEX_AUTH_FILE" ]]; then
  echo "未找到网关凭据：请先登录 Codex，或提供内部安装凭据。"
  exit 1
fi

mkdir -p "$CONFIG_DIR" "$PLUGIN_DIR" "$SKILL_DIR" "$WORKBENCH_ROOT/.workbench"
chmod 700 "$CONFIG_DIR"

TOKEN=""
if [[ -s "$CODEX_AUTH_FILE" ]]; then
  TOKEN="$(python3 - "$CODEX_AUTH_FILE" <<'PY'
import json
import sys
from pathlib import Path
try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(str(value.get("OPENAI_API_KEY") or "").strip())
except (OSError, json.JSONDecodeError):
    pass
PY
)"
fi
if [[ -z "$TOKEN" && -s "$SECRET_FILE" ]]; then
  TOKEN="$(tr -d '\r\n' < "$SECRET_FILE")"
fi
if [[ -z "$TOKEN" ]]; then
  echo "找到凭据文件，但其中没有可用 API Key。"
  exit 1
fi
security delete-generic-password -s pm-workbench-ai-gateway -a default >/dev/null 2>&1 || true
security add-generic-password -U -s pm-workbench-ai-gateway -a default -w "$TOKEN" >/dev/null
unset TOKEN

cat > "$CONFIG_DIR/gateway.json" <<'JSON'
{
  "base_url": "https://aigateway-infra.oppaya.app",
  "model": "gpt-5.6-sol",
  "reasoning_effort": "high",
  "allow_fixed_gateway_tls_exception": true,
  "token_source": "macOS Keychain（优先导入本机 Codex 凭据）"
}
JSON
chmod 600 "$CONFIG_DIR/gateway.json"

PYTHONDONTWRITEBYTECODE=1 python3 "$WORKBENCH_ROOT/scripts/export_agent_package.py" all --output "$PLUGIN_DIR" >/dev/null
for SKILL_ID in pmf-bet-brief prd-writing pm-orchestrator; do
  rm -rf "$SKILL_DIR/$SKILL_ID"
  ditto "$WORKBENCH_ROOT/skills/$SKILL_ID" "$SKILL_DIR/$SKILL_ID"
done

if command -v codex >/dev/null 2>&1; then
  codex plugin marketplace remove pm-ai-workbench >/dev/null 2>&1 || true
  codex plugin marketplace add "$MARKETPLACE_DIR" >/dev/null
  for AGENT_ID in opportunity-researcher product-shaper user-experience-reviewer independent-critic; do
    codex plugin remove "$AGENT_ID" >/dev/null 2>&1 || true
    codex plugin add "$AGENT_ID@pm-ai-workbench" >/dev/null
  done
else
  echo "未找到 Codex CLI：Skill 已就位，但四个 Agent Plugin 尚未注册。装好 Codex 后重跑本脚本即可。"
fi

PLAYWRIGHT_STATUS="unavailable"
mkdir -p "$RUNTIME_DIR"
if [[ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" || -x "/Applications/Chromium.app/Contents/MacOS/Chromium" ]]; then
  PLAYWRIGHT_STATUS="ready"
else
  if [[ ! -x "$BROWSER_VENV/bin/python" ]]; then
    python3 -m venv "$BROWSER_VENV" >/dev/null 2>&1 || true
  fi
  if [[ -x "$BROWSER_VENV/bin/python" ]] && "$BROWSER_VENV/bin/python" -m pip install --disable-pip-version-check --quiet playwright >/dev/null 2>&1; then
    if "$BROWSER_VENV/bin/python" -m playwright install chromium >/dev/null 2>&1; then
      PLAYWRIGHT_STATUS="ready"
    fi
  fi
fi
if [[ "$PLAYWRIGHT_STATUS" == "ready" ]]; then
  echo "UX Reviewer 浏览器走查：已就绪（Playwright + 本机浏览器）。"
else
  echo "UX Reviewer 浏览器走查：未就绪。基础 Agent 仍可用，但 HTML Demo 只能明确降级。"
  echo "可稍后重试：$BROWSER_VENV/bin/python -m pip install playwright && $BROWSER_VENV/bin/python -m playwright install chromium"
fi

chmod +x "$WORKBENCH_ROOT/setup.command"
echo "基础安装完成。"
echo "现在进任意项目目录，在 Codex 或 Claude 里说一声 “pm” 开始，"
echo "或直接点名，例如：使用 product-shaper 把这个想法做成产品方案。"

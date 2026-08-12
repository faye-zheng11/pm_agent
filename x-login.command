#!/bin/zsh
# X(Twitter) live 抓取 · 账号配置与登录（用 twscrape）。
# 你的 X 凭据只写进本机 runtime/vendor/x-accounts.txt（已 gitignore），我/仓库都不碰。
# ⚠️ 仅个人研究用途、账号风险自负。X 反爬最凶：登录常需邮箱验证码/2FA，最不稳。
set -uo pipefail

ROOT="${0:A:h}"
VENDOR="$ROOT/runtime/vendor"
ACCT="$VENDOR/x-accounts.txt"
DB="$VENDOR/x-accounts.db"
export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$VENDOR"

echo "=== X(Twitter) live 抓取 · 登录 ==="

# 1) 确保 uv + twscrape
if ! command -v uv >/dev/null 2>&1; then
  echo "· 安装 uv…"; curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || { echo "uv 安装失败"; exit 1; }
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v twscrape >/dev/null 2>&1; then
  echo "· 安装 twscrape…"; uv tool install twscrape >/dev/null 2>&1 || { echo "twscrape 安装失败"; exit 1; }
fi

# 2) 需要账号文件
if [[ ! -s "$ACCT" ]]; then
  cat > "$ACCT" <<'TXT'
# 每行一个 X 账号，字段用冒号分隔，顺序：
# username:password:email:email_password
# 例：
# myhandle:MyPassw0rd:my@mail.com:MyMailAppPassword
# 说明：email_password 建议用邮箱的“应用专用密码”，twscrape 用它自动读登录验证码。
# 填好后保存，再次运行本文件。本文件已被 .gitignore 忽略，不会进仓库。
TXT
  echo
  echo ">> 已生成模板：$ACCT"
  echo ">> 请填入你的 X 账号（username:password:email:email_password），保存后【重新运行本文件】。"
  exit 0
fi

# 3) 加账号 + 登录
echo "· 导入账号并登录（可能需要几十秒，X 可能要求邮箱验证码）…"
twscrape --db "$DB" add_accounts "$ACCT" username:password:email:email_password || true
if twscrape --db "$DB" login_accounts; then
  echo
  echo "✅ X 账号已登录。以后 researcher 会用它自动 live 抓 X。"
  echo "   若日后提示 x_login_required，重新运行本文件（或检查账号是否被 X 限制）。"
else
  echo
  echo "⚠️ 登录未全部成功。X 常因风控/2FA/验证码拒绝自动登录——这是 X 平台限制，不是脚本问题。"
  echo "   可查看 twscrape --db \"$DB\" accounts 的状态；必要时换账号或稍后重试。"
fi

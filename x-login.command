#!/bin/zsh
# X(Twitter) live 抓取 · cookie 登录（用 twscrape，绕开密码/2FA，最稳）。
# 你把 x.com 的 Cookie（含 auth_token、ct0）存到 runtime/vendor/x-cookie.txt，本脚本导入。
# 凭据只在本机、已 gitignore、绝不入库。⚠️ 仅个人研究用途、账号风险自负。
set -uo pipefail

ROOT="${0:A:h}"
VENDOR="$ROOT/runtime/vendor"
CK="$VENDOR/x-cookie.txt"
DB="$VENDOR/x-accounts.db"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
mkdir -p "$VENDOR"

echo "=== X(Twitter) live 抓取 · cookie 登录 ==="

# 1) 确保 uv + twscrape
if ! command -v uv >/dev/null 2>&1; then
  echo "· 安装 uv…"; curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || { echo "uv 安装失败"; exit 1; }
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v twscrape >/dev/null 2>&1; then
  echo "· 安装 twscrape…"; uv tool install twscrape >/dev/null 2>&1 || { echo "twscrape 安装失败"; exit 1; }
fi

# 2) 有含 auth_token 的 cookie 文件就导入
if [[ -s "$CK" ]] && grep -qi 'auth_token=' "$CK"; then
  echo "· 导入 cookie（含 auth_token/ct0）…"
  tr -d '\r\n' < "$CK" | sed -e 's/^Cookie:[[:space:]]*//I' -e "s/^['\"]//" -e "s/['\"]$//" \
    | twscrape --db "$DB" add_cookie x-main
  echo
  echo "· 当前 X 账号状态："
  twscrape --db "$DB" accounts
  echo
  echo "✅ 若上面显示 active=True，X 就绪；researcher 会自动 live 抓 X。"
  echo "   cookie 失效时重抓一次 x.com 的 cookie 覆盖 $CK，再运行本文件。"
  exit 0
fi

# 3) 否则给模板 + 说明
cat > "$CK" <<'TXT'
在这里贴 x.com 的完整 Cookie（一整行，至少包含 auth_token= 和 ct0=），然后保存、重新运行本文件。
获取方法（和微博的 Network 法一样）：
  1. Chrome 打开 https://x.com 并登录；
  2. ⌥⌘I 开 DevTools → Network(网络) → ⌘R 刷新 → 点任意 x.com 请求；
  3. Request Headers → Cookie 那行 → 右键 Copy value（会包含 HttpOnly 的 auth_token）；
  4. 用那一整串覆盖本文件全部内容（把这几行说明也删掉），保存。
本文件已被 .gitignore 忽略，不会进仓库。
TXT
echo ">> 已生成模板：$CK"
echo ">> 请把 x.com 的 Cookie（含 auth_token、ct0）贴进去覆盖说明文字，保存后【重新运行本文件】。"
echo ">> 最快：复制好 Cookie 后运行  pbpaste > \"$CK\"  再运行本文件。"

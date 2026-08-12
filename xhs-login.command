#!/bin/zsh
# 小红书 live 抓取：一次性登录（含首次自动安装）。
# 仅个人研究用途、遵守平台规则、账号风险自负。凭据只存本机、绝不进仓库。
set -uo pipefail

ROOT="${0:A:h}"
MC="$ROOT/runtime/vendor/MediaCrawler"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"

echo "=== 小红书 live 抓取 · 登录/安装 ==="

# 1) 确保 uv
if ! command -v uv >/dev/null 2>&1; then
  echo "· 安装 uv（Python 环境管理器）…"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || { echo "uv 安装失败，请手动安装 https://astral.sh/uv"; exit 1; }
  export PATH="$HOME/.local/bin:$PATH"
fi

# 2) 确保 MediaCrawler
if [[ ! -d "$MC/.git" ]]; then
  echo "· 下载 MediaCrawler（小红书抓取器）…"
  mkdir -p "$ROOT/runtime/vendor"
  git clone --depth 1 https://github.com/NanmiCoder/MediaCrawler "$MC" || { echo "clone 失败，请检查网络"; exit 1; }
fi

# 3) 安装依赖 + 浏览器
echo "· 安装依赖（首次较慢）…"
( cd "$MC" && uv sync >/dev/null 2>&1 ) || { echo "依赖安装失败"; exit 1; }
( cd "$MC" && uv run playwright install chromium >/dev/null 2>&1 ) || true

# 4) 打开可见浏览器扫码登录（会话持久化到 xhs_user_data_dir，之后自动复用）
echo
echo ">> 即将打开浏览器。请用【小红书 App】扫码登录。"
echo ">> 登录后会试抓 2 条笔记作为验证，然后即可关闭。"
echo
cd "$MC"
uv run python main.py --platform xhs --lt qrcode --type search --keywords "kpop" \
  --crawler_max_notes_count 2 --get_comment no --headless no \
  --save_data_option json --save_data_path "$MC/data/_login_probe"

echo
echo "✅ 登录会话已保存到本机。以后 researcher 会用它自动 live 抓小红书。"
echo "   若日后提示 xhs_login_required，重新双击本文件扫码即可。"

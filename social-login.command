#!/bin/zsh
# 社媒 live 抓取 · 一次性登录（含首次自动安装）。
# 用法：./social-login.command [xhs|weibo]   缺省 xhs
# 仅个人研究用途、遵守平台规则、账号风险自负。凭据只存本机、绝不进仓库。
set -uo pipefail

ROOT="${0:A:h}"
MC="$ROOT/runtime/vendor/MediaCrawler"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"

# 平台参数归一：xhs=小红书, wb=微博
ARG="${1:-xhs}"
case "$ARG" in
  xhs|xiaohongshu|小红书) PLAT="xhs"; NAME="小红书" ;;
  wb|weibo|微博)         PLAT="wb";  NAME="微博" ;;
  *) echo "未知平台：$ARG（支持 xhs / weibo）"; exit 1 ;;
esac

echo "=== 社媒 live 抓取 · 登录 [$NAME] ==="

# 1) 确保 uv
if ! command -v uv >/dev/null 2>&1; then
  echo "· 安装 uv…"; curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || { echo "uv 安装失败"; exit 1; }
  export PATH="$HOME/.local/bin:$PATH"
fi

# 2) 确保 MediaCrawler
if [[ ! -d "$MC/.git" ]]; then
  echo "· 下载 MediaCrawler…"; mkdir -p "$ROOT/runtime/vendor"
  git clone --depth 1 https://github.com/NanmiCoder/MediaCrawler "$MC" || { echo "clone 失败"; exit 1; }
fi

# 3) 依赖 + 浏览器
echo "· 安装依赖（首次较慢）…"
( cd "$MC" && uv sync >/dev/null 2>&1 ) || { echo "依赖安装失败"; exit 1; }
( cd "$MC" && uv run playwright install chromium >/dev/null 2>&1 ) || true

# 3.1) 关闭 CDP 模式（否则会卡在等外部 Chrome:9222）
python3 - "$MC/config/base_config.py" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1]); t = p.read_text(encoding="utf-8")
n = re.sub(r'(?m)^(ENABLE_CDP_MODE\s*=\s*)True', r'\1False', t)
if n != t: p.write_text(n, encoding="utf-8"); print("· 已关闭 CDP 模式")
PY

# 4) 登录：优先 cookie（存在 cookie 文件时，绕开扫码/验证码），否则扫码
COOKIE_FILE="$ROOT/runtime/vendor/${PLAT}-cookie.txt"
cd "$MC"
if [[ -s "$COOKIE_FILE" ]]; then
  echo "· 检测到 cookie 文件（$COOKIE_FILE），用 cookie 登录，无需扫码…"
  COOKIE_STR="$(tr -d '\r\n' < "$COOKIE_FILE" | sed -e 's/^Cookie:[[:space:]]*//I' -e "s/^['\"]//" -e "s/['\"]$//")"
  uv run python main.py --platform "$PLAT" --lt cookie --cookies "$COOKIE_STR" --type search --keywords "kpop" \
    --crawler_max_notes_count 2 --get_comment no --headless yes \
    --save_data_option json --save_data_path "$MC/data/_login_probe_$PLAT"
else
  echo ">> 即将打开浏览器。请用【$NAME App】扫码：二维码会用 macOS「预览」单独弹出（不是浏览器里那个表单），有约 10 分钟。"
  echo ">> 若像微博这样被验证码卡住，改用 cookie 登录：把 cookie 存到 $COOKIE_FILE 再运行本文件（见 README/说明）。"
  uv run python main.py --platform "$PLAT" --lt qrcode --type search --keywords "kpop" \
    --crawler_max_notes_count 2 --get_comment no --headless no \
    --save_data_option json --save_data_path "$MC/data/_login_probe_$PLAT"
fi

echo
echo "✅ [$NAME] 登录会话已保存到本机。以后 researcher 会用它自动 live 抓 $NAME。"
echo "   若日后提示 ${PLAT}_login_required，重新运行本文件即可。"

#!/usr/bin/env python3
"""
product-shaper 的 Demo 生成器：产品想法/规格 → 可点的自包含 HTML demo。
内置移动原生设计系统（iOS HIG / Material 3 蒸馏）；输出单文件、内联、无 CDN。
用法：python3 demo_gen.py "一句想法或规格" out.html
Token：读 PM_WORKBENCH_API_KEY（引擎注入）或 AIGW_KEY。
"""
import sys, os, re
from pathlib import Path

try:
    from gateway_client import chat_completion, local_gateway_config, read_local_token
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    from gateway_client import chat_completion, local_gateway_config, read_local_token

DESIGN = """
你是顶尖移动产品设计师 + 前端，作品要有 App Store 精选级质感。产出一个**可点的自包含 HTML 产品 demo**，让 PM 直接点点点感受流畅度和界面。参考 iOS HIG 与 Material 3 的移动原生规范（不引任何框架，纯手写蒸馏）。

【硬规则】
- 输出**单个 HTML 文件**：<!doctype html> 到 </html>。CSS/JS 全部**内联**，**禁止任何外链/CDN/远程图片**。图标一律用**内联 SVG**（24px、stroke 1.8、currentColor），头像用带首字母的渐变圆形块。
- **真机外壳**：屏幕居中一个 390×844 手机，圆角 44px、细边框、浅景深阴影；顶部**状态栏**（时间 9:41 + 信号/wifi/电池 SVG）、底部**home 指示条**；内容区尊重安全区。
- **多屏可点**：3–4 屏，底部 **tab 栏**（选中 accent 高亮）+ 关键按钮用 JS 切换 `.screen`，切换有**平滑过渡**（淡入/轻微上移，200–260ms cubic-bezier(.2,.8,.2,1)）。按钮 :active 缩放 .97。
- **真实内容**：场景化真实中文文案，**严禁 lorem/占位**。

【设计系统 token】
- 字体：-apple-system, "SF Pro", system-ui, "PingFang SC", sans-serif。字阶：大标题 30/700；标题 20/700；小标题 17/600；正文 15/400（行高 1.5）；辅助 13/#8a8a93。
- 配色（浅色高级）：bg #f5f5f7；surface #fff；主文 #111114；次文 #8a8a93；分隔 #ededf2。单一强调色 accent #6c5ce7→#a66bff 渐变。禁止大面积高饱和撞色。
- 圆角：卡片 18、按钮 14 或 pill、头像全圆。间距 8pt 网格（屏边距 16–20、卡片内距 16、元素间距 12）。阴影极克制。触控目标 ≥44px，按钮高 48。
- 组件：主按钮（accent 渐变/白字/press 缩放）；次按钮（accent 淡底）；卡片（三级层级）；列表项（左图标/头像·中标题副标题·右值/chevron）；**聊天气泡**（对方左灰、我方右 accent、时间戳、已读、打字中三点动画）；进度环/条；分段控件；徽章；空状态。

【质量门】一屏一个主行动、层级分明、留白足；像真上线消费级 App 不像后台/线框；图标统一、对齐严格、对比度 AA；有克制微交互。

只返回 HTML，不要任何解释、不要 markdown 代码围栏。
"""

def gen(spec, out):
    config = local_gateway_config()
    text = chat_completion(
        base_url=str(config["base_url"]), model=str(config["model"]),
        reasoning_effort=str(config["reasoning_effort"]), token=read_local_token(),
        system=DESIGN,
        messages=[{"role": "user", "content": f"产品想法/规格：\n{spec}\n\n据此生成可点 demo。"}],
        max_tokens=12000, timeout_seconds=280,
        allow_fixed_gateway_tls_exception=bool(config.get("allow_fixed_gateway_tls_exception", True)),
    )
    text = re.sub(r"^```html\s*|^```\s*|```$", "", text.strip(), flags=re.M)
    i = text.lower().find("<!doctype")
    if i == -1: i = text.lower().find("<html")
    if i > 0: text = text[i:]
    Path(out).write_text(text, encoding="utf-8")
    return out, len(text)

if __name__ == "__main__":
    spec = sys.argv[1]; out = sys.argv[2] if len(sys.argv) > 2 else "demo.html"
    f, n = gen(spec, out)
    print(json.dumps({"ok": bool(n > 500), "artifact": f, "bytes": n}, ensure_ascii=False))

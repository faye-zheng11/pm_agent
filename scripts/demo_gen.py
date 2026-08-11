#!/usr/bin/env python3
"""
product-shaper 的 Demo 生成器：产品想法/规格 → 可点的自包含 HTML demo。
内置设计系统（美观 skill）；输出单文件、内联、无 CDN、移动端 app 框架、多屏可点。
用法：python3 scripts/demo_gen.py "一句想法或规格" out.html
"""
import sys, os, re
from pathlib import Path

try:
    from gateway_client import chat_completion, local_gateway_config, read_local_token
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from gateway_client import chat_completion, local_gateway_config, read_local_token

DESIGN = """
你是顶尖移动产品设计师 + 前端，作品要有 App Store 精选级质感。产出一个**可点的自包含 HTML 产品 demo**，让 PM 直接点点点感受流畅度和界面。参考 iOS HIG 与 Material 3 的移动原生规范（不引任何框架，纯手写蒸馏）。

【硬规则】
- 输出**单个 HTML 文件**：<!doctype html> 到 </html>。CSS/JS 全部**内联**，**禁止任何外链/CDN/远程图片**。图标一律用**内联 SVG**（24px、stroke 1.8、currentColor），头像用带首字母的渐变圆形块。
- **真机外壳**：屏幕居中一个 390×844 手机，圆角 44px、细边框、浅景深阴影；顶部**状态栏**（时间 9:41 + 信号/wifi/电池 SVG）、底部**home 指示条**；内容区尊重安全区。
- **多屏可点**：3–4 屏（如 首页/聊天/回忆/我的），底部 **tab 栏**（4 项，选中 accent 高亮 + 图标微动）+ 关键按钮用 JS 切换 `.screen`，切换有**平滑过渡**（淡入/轻微上移，200–260ms cubic-bezier(.2,.8,.2,1)）。按钮 :active 缩放 .97。
- **真实内容**：场景化真实中文文案，**严禁 lorem/占位**；消息、数字、时间、卡片都像线上真数据。

【设计系统 token】
- 字体：-apple-system, "SF Pro", system-ui, "PingFang SC", sans-serif。字阶：大标题 30/700；标题 20/700；小标题 17/600；正文 15/400（行高 1.5）；辅助 13/#8a8a93。
- 配色（浅色，克制高级）：bg #f5f5f7；surface #fff；主文 #111114；次文 #8a8a93；分隔 #ededf2。**单一强调色** accent #6c5ce7→#a66bff 渐变；语义色克制。禁止大面积高饱和撞色。
- 圆角：卡片 18、按钮 14 或 pill、输入 12、头像全圆。间距 **8pt 网格**：屏边距 16–20，卡片内距 16，元素间距 12。阴影极克制（卡片 0 1px 3px rgba(0,0,0,.05)；浮层 0 10px 30px rgba(0,0,0,.12)）。
- **触控目标 ≥44px**；按钮高 48。
- 组件规格：主按钮（accent 渐变/白字/48 高/press 缩放）；次按钮（accent 淡底）；卡片（标题+副标题+meta 三级层级）；列表项（左 SVG/头像 · 中 标题+副标题 · 右 值/chevron）；**聊天气泡**（对方左灰、我方右 accent、小尾巴、时间戳、已读、打字中三点动画）；**进度环/条**（关系等级用）；分段控件；徽章/胶囊标签；空状态。

【质量门（必须做到，否则算不合格）】
1. 一屏一个明确主行动，视觉层级一眼分明；留白充足，不塞满。
2. 像**真上线的消费级 App**，不是后台管理、不是线框、不是网页感。
3. 图标统一、对齐严格、间距一致；对比度达 AA。
4. 有克制的微交互与过渡，点哪都有反馈。

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
    text = re.sub(r"^```html\s*|^```\s*|```$", "", text.strip(), flags=re.M)  # 去围栏（若有）
    i = text.lower().find("<!doctype");
    if i == -1: i = text.lower().find("<html")
    if i > 0: text = text[i:]
    Path(out).write_text(text, encoding="utf-8")
    return out, len(text)

if __name__ == "__main__":
    spec = sys.argv[1]; out = sys.argv[2] if len(sys.argv) > 2 else "demo.html"
    f, n = gen(spec, out)
    print(f"✓ 生成 {f}（{n} 字节）")

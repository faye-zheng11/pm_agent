#!/usr/bin/env python3
"""
UX-reviewer 的 persona 反应器：以你选的粉丝群体视角，模拟真实用户用 demo，
挑优点/痛点/会在哪放弃，转成真人研究问题。明确标注"模拟≠真实验证"。
用法：python3 scripts/ux_review.py <demo.html> <persona_key>
"""
import sys, os, re
from pathlib import Path

try:
    from gateway_client import chat_completion, local_gateway_config, read_local_token
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    from gateway_client import chat_completion, local_gateway_config, read_local_token

# ── K-pop 粉丝群体库（可换）───────────────────────────────
PERSONAS = {
 "唯粉":   "只嗑一个成员的唯粉。要的是与'我的人'专属、深度的一对一关系；最在意 AI 是否真的像 TA、有没有背叛唯一感（别的成员乱入就翻车）。",
 "团粉":   "喜欢整个团体的团粉。关注成员之间的协作、内容完整性和群体氛围；对只围绕单一成员的默认路径会觉得被排除。",
 "妈粉":   "把爱豆当孩子疼的妈粉。要的是守护、心疼、纯粹；对'恋爱向/心动值/养成'这类容易联想到情感操控或商业化的设计高度警惕，反感被套路氪金。",
 "cp粉":   "嗑两个爱豆 CP 的 cp粉。核心兴趣是两人之间的关系动态，单人一对一陪伴对 TA 吸引力有限；会问'能不能有互动/名场面'。",
 "CP粉":   "嗑两个爱豆 CP 的 CP 粉。核心兴趣是两人之间的关系动态，单人一对一陪伴对 TA 吸引力有限；会问'能不能有互动/名场面'。",
 "事业粉": "只关心爱豆事业和数据的事业粉。对拟社会陪伴本身不感冒，会问'这对爱豆本人有什么好处/会不会污名化'。",
 "颜粉":   "颜值粉，为好看而来。第一眼看视觉质感、立绘、界面精致度；内容深度其次。",
 "teen":  "15-18 岁学生粉，零花钱有限、时间碎片、情绪浓烈；对付费敏感，对'被理解、被回应'的情绪价值需求强。",
 "海外粉": "东南亚/欧美海外粉，可能有语言和文化语境差异；在意本地化、时区、内容是否照顾非中文语境。",
}

def demo_text(path):
    h = open(path, encoding="utf-8").read()
    h = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S)
    txt = re.sub(r"<[^>]+>", " ", h)
    txt = re.sub(r"\s+", " ", txt)
    return txt[:3500]

def review(demo, persona_key):
    persona = PERSONAS.get(persona_key, persona_key)
    config = local_gateway_config()
    system = f"""你是 user-experience-reviewer，现在**模拟一个真实的 [{persona_key}]** 来用这个 demo：
{persona}

规则：
- 以这个群体的真实心态走查界面，给：第一印象、逐屏的优点/痛点/会在哪一步放弃或反感、整体接受度（爱用/一般/劝退）。
- 特别指出对**这个群体**特有的雷点和爽点（不同群体反应不同）。
- 每条重要问题 → 转成一个可以去问真人的研究问题。
- 结尾：一句话判断"这个群体是不是它的菜"。
- 硬边界：**这是模拟，不是真实用户验证**，不能当作 PMF 证据；该找真人验证的地方标清楚。用中文。"""
    text = chat_completion(
        base_url=str(config["base_url"]), model=str(config["model"]),
        reasoning_effort=str(config["reasoning_effort"]), token=read_local_token(),
        system=system,
        messages=[{"role": "user", "content": "demo 各屏的可见内容如下（提取自 HTML）：\n" + demo_text(demo)}],
        max_tokens=5000, timeout_seconds=240,
        allow_fixed_gateway_tls_exception=bool(config.get("allow_fixed_gateway_tls_exception", True)),
    )
    print(text)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("可选群体：", " ".join(PERSONAS)); sys.exit()
    review(sys.argv[1], sys.argv[2])

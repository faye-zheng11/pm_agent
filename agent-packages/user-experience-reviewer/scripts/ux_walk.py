#!/usr/bin/env python3
"""
UX-reviewer 的客观走查器：真打开 HTML demo，点每个屏，桌面+手机截图，
检测横向溢出 / 元素遮挡 / 0 尺寸 / 死按钮，输出结构化 findings。
依赖：pip install playwright && playwright install chromium
用法：python3 scripts/ux_walk.py <demo.html> [输出目录]
"""
import sys, os, json, asyncio

VIEWPORTS = {"desktop": (1280, 800), "mobile": (390, 844)}

async def walk(demo_path, outdir):
    from playwright.async_api import async_playwright
    os.makedirs(outdir, exist_ok=True)
    url = "file://" + os.path.abspath(demo_path)
    findings = {"demo": demo_path, "viewports": {}, "issues": []}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for vp, (w, h) in VIEWPORTS.items():
            page = await browser.new_page(viewport={"width": w, "height": h})
            await page.goto(url); await page.wait_for_timeout(400)
            shots = []
            # 找可点的 tab/按钮
            clickables = await page.query_selector_all(
                "[data-screen],[onclick],.tab,nav a,nav button,button")
            labels = []
            for i, el in enumerate(clickables[:8]):
                try:
                    txt = (await el.inner_text())[:12]
                    await el.click(timeout=1500); await page.wait_for_timeout(250)
                    shot = os.path.join(outdir, f"{vp}_{i}_{txt or 'click'}.png")
                    await page.screenshot(path=shot); shots.append(shot); labels.append(txt)
                except Exception:
                    pass
            # 横向溢出
            overflow = await page.evaluate(
                "() => document.documentElement.scrollWidth > window.innerWidth + 2")
            if overflow:
                findings["issues"].append({"viewport": vp, "type": "horizontal_overflow",
                    "detail": "内容横向溢出，出现横向滚动"})
            # 0 尺寸、屏外和同层重叠可点元素（潜在遮挡/死按钮）。
            interactive = await page.evaluate("""() => {
                const nodes = [...document.querySelectorAll('button,a,[onclick]')];
                const visible = nodes.map((e, index) => {
                    const r = e.getBoundingClientRect();
                    const style = getComputedStyle(e);
                    return {index, label: (e.innerText || e.getAttribute('aria-label') || e.className || '').slice(0, 32),
                        left:r.left, top:r.top, right:r.right, bottom:r.bottom,
                        width:r.width, height:r.height,
                        visible: style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0};
                }).filter(item => item.visible);
                const bad = visible.filter(item => item.width < 2 || item.height < 2 || item.right < 0 || item.bottom < 0 || item.left > innerWidth || item.top > innerHeight);
                const overlaps = [];
                for (let i = 0; i < visible.length; i++) for (let j = i + 1; j < visible.length; j++) {
                    const a = visible[i], b = visible[j];
                    const area = Math.max(0, Math.min(a.right,b.right)-Math.max(a.left,b.left)) * Math.max(0, Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top));
                    const smaller = Math.min(a.width*a.height, b.width*b.height);
                    if (area > 4 && smaller > 0 && area / smaller > 0.35) overlaps.push({first:a.label, second:b.label, overlap_ratio:Number((area/smaller).toFixed(2))});
                }
                return {bad: bad.slice(0, 12), overlaps: overlaps.slice(0, 12)};
            }""")
            if interactive["bad"]:
                findings["issues"].append({"viewport": vp, "type": "zero_size_or_occluded",
                    "detail": f"疑似不可见/屏外的可点元素：{interactive['bad']}"})
            if interactive["overlaps"]:
                findings["issues"].append({"viewport": vp, "type": "overlap_or_occluded",
                    "detail": f"可点元素存在明显重叠，可能互相遮挡：{interactive['overlaps']}"})
            findings["viewports"][vp] = {"clicked": labels, "screenshots": shots}
            await page.close()
        await browser.close()
    json.dump(findings, open(os.path.join(outdir, "findings.json"), "w"),
              ensure_ascii=False, indent=2)
    print(json.dumps(findings, ensure_ascii=False, indent=2))
    return findings

if __name__ == "__main__":
    demo = sys.argv[1]; outdir = sys.argv[2] if len(sys.argv) > 2 else "ux_walk_out"
    asyncio.run(walk(demo, outdir))

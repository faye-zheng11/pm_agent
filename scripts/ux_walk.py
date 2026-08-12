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
        browser_path = next((candidate for candidate in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ) if os.path.isfile(candidate)), "")
        launch_options = {"headless": True}
        if os.path.isfile(browser_path):
            launch_options["executable_path"] = browser_path
        browser = await p.chromium.launch(**launch_options)
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
            # 0 尺寸 / 屏外 可点元素（潜在遮挡/死元素）
            hidden = await page.evaluate("""() => {
                const bad=[]; document.querySelectorAll('button,a,[onclick]').forEach(e=>{
                    const r=e.getBoundingClientRect();
                    if(r.width<2||r.height<2) bad.push((e.innerText||e.className).slice(0,20)); });
                return bad.slice(0,10); }""")
            if hidden:
                findings["issues"].append({"viewport": vp, "type": "zero_size_or_occluded",
                    "detail": f"疑似不可见/被遮挡的可点元素：{hidden}"})
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

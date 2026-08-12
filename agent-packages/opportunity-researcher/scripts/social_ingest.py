#!/usr/bin/env python3
"""
社媒帖子采集 → 归一 → 喂 opportunity-researcher。采集与 agent 解耦。
用法：
  python3 social_ingest.py reddit "kpop parasocial" --limit 8
  python3 social_ingest.py xhs-live "痛包" --limit 15   # 真·live 抓小红书(需先运行 xhs-login.command 扫码登录)
  python3 social_ingest.py mediacrawler <导出.json>
  python3 social_ingest.py x <twscrape导出.json>
  python3 social_ingest.py manual
不带 --project 时把归一后的 JSON 打到 stdout（供引擎读取）；带 --project 落盘去重。
Token：读 PM_WORKBENCH_API_KEY 或 ~/.config/pm-workbench/tavily-api-key。
"""
import sys, os, json, ssl, hashlib, datetime, urllib.request, subprocess, shutil, pathlib

def _tavily_key():
    for env in ("TAVILY_API_KEY",):
        if os.environ.get(env): return os.environ[env].strip()
    p = os.path.expanduser("~/.config/pm-workbench/tavily-api-key")
    return open(p).read().strip() if os.path.exists(p) else ""

def normalize(platform, author, title, text, created, url, engagement, source_query=""):
    pid = "sp_" + hashlib.sha1((url or (title + text)).encode()).hexdigest()[:12]
    return {"id": pid, "platform": platform, "author": author, "title": title or "",
            "text": (text or "")[:2000], "created": created or "", "url": url or "",
            "engagement": engagement or {}, "source_query": source_query,
            "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "evidence_tier": "B",
            "note": "公开讨论=观察信号，不等于真实需求；由 opportunity-researcher 再评分"}

def source_reddit(query, limit=8):
    key = _tavily_key()
    ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    body = json.dumps({"api_key": key, "query": f"{query} site:reddit.com",
                       "max_results": limit, "search_depth": "advanced"}).encode()
    out = []
    for _ in range(3):
        req = urllib.request.Request("https://api.tavily.com/search", data=body,
                                     headers={"Content-Type": "application/json"})
        data = json.loads(urllib.request.urlopen(req, timeout=40, context=ctx).read())
        for r in data.get("results", []):
            u = r.get("url", "")
            if "reddit.com" not in u or "/comments/" not in u: continue
            out.append(normalize("reddit", "reddit-user", r.get("title"), r.get("content"),
                                 "", u, {"relevance": round(r.get("score", 0), 2)}, query))
        if out: break
    return out

def _ts(v):
    try:
        n = int(v)
        if n > 1e12: n //= 1000
        return datetime.datetime.utcfromtimestamp(n).strftime("%Y-%m-%d")
    except Exception:
        return str(v or "")

def source_mediacrawler(path):
    rows = json.load(open(path, encoding="utf-8"))
    if isinstance(rows, dict): rows = rows.get("data", [rows])
    out = []
    for p in rows:
        if p.get("comment_id") or ("content" in p and "title" not in p):
            out.append(normalize("xiaohongshu", p.get("nickname",""), "", p.get("content",""),
                _ts(p.get("create_time")),
                p.get("note_url") or ("https://www.xiaohongshu.com/discovery/item/"+str(p.get("note_id",""))),
                {"likes": p.get("like_count"), "sub_comments": p.get("sub_comment_count")}, "mediacrawler-comment"))
        else:
            out.append(normalize("xiaohongshu", p.get("nickname",""), p.get("title",""),
                p.get("desc") or p.get("content",""), _ts(p.get("time") or p.get("last_modify_ts")),
                p.get("note_url",""),
                {"likes": p.get("liked_count"), "collects": p.get("collected_count"),
                 "comments": p.get("comment_count"), "shares": p.get("share_count")}, "mediacrawler-note"))
    return out

def _mediacrawler_dir():
    return pathlib.Path(__file__).resolve().parents[3] / "runtime" / "vendor" / "MediaCrawler"

def _mc_scrape(platform, keyword, limit, timeout):
    """跑 MediaCrawler 按关键词 live 搜（platform: xhs=小红书 / wb=微博）。
    仅个人研究用途、遵守平台规则、账号风险自负。返回 (json 文件列表, 日志)。"""
    mc = _mediacrawler_dir()
    uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    if not mc.is_dir() or not (mc / ".venv").is_dir() or not os.path.exists(uv):
        raise SystemExit(f"{platform}_not_installed：未安装抓取器，先运行 social-login.command {platform}")
    outdir = mc / "data" / f"_live_{platform}"
    shutil.rmtree(outdir, ignore_errors=True); outdir.mkdir(parents=True, exist_ok=True)
    limit = min(max(int(limit), 1), 20)
    cmd = [uv, "run", "python", "main.py", "--platform", platform, "--lt", "qrcode",
           "--type", "search", "--keywords", keyword, "--save_data_option", "json",
           "--save_data_path", str(outdir), "--crawler_max_notes_count", str(limit),
           "--get_comment", "yes", "--get_sub_comment", "no", "--headless", "yes"]
    try:
        proc = subprocess.run(cmd, cwd=str(mc), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"{platform}_login_required：抓取超时（多半是会话失效/反爬），请运行 social-login.command {platform} 重新扫码")
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return sorted(outdir.rglob("*.json")), blob

def _login_or_no_result(platform, blob):
    low = blob.lower()
    if any(k in blob for k in ("扫码", "二维码", "重新登录", "登录失效", "未登录")) or \
       any(k in low for k in ("login", "qrcode", "scan", "relogin", "not login")):
        raise SystemExit(f"{platform}_login_required：会话失效，请运行 social-login.command {platform} 扫码登录后重试")
    raise SystemExit(f"{platform}_no_result：本次未抓到内容（关键词无结果或被风控）：" + blob.strip()[-400:])

def source_xhs_live(keyword, limit=15, timeout=220):
    """真·live 抓小红书笔记+一级评论。会话失效抛 xhs_login_required。"""
    files, blob = _mc_scrape("xhs", keyword, limit, timeout)
    posts = []
    for jf in files:
        try: posts += source_mediacrawler(str(jf))
        except Exception: continue
    if not posts: _login_or_no_result("xhs", blob)
    return posts

def source_mediacrawler_weibo(path):
    rows = json.load(open(path, encoding="utf-8"))
    if isinstance(rows, dict): rows = rows.get("data", [rows])
    out = []
    for p in rows:
        is_comment = bool(p.get("comment_id"))
        url = p.get("note_url") or (f"https://m.weibo.cn/detail/{p.get('note_id')}" if p.get("note_id") else "")
        out.append(normalize("weibo", p.get("nickname", ""), "", p.get("content", ""),
            _ts(p.get("create_time")), url,
            {"likes": p.get("liked_count") or p.get("like_count"),
             "comments": p.get("comments_count"), "shares": p.get("shared_count")},
            "mediacrawler-weibo-comment" if is_comment else "mediacrawler-weibo-note"))
    return out

def source_wb_live(keyword, limit=15, timeout=220):
    """真·live 抓微博（含 K-pop 超话/话题讨论）。会话失效抛 wb_login_required。"""
    files, blob = _mc_scrape("wb", keyword, limit, timeout)
    posts = []
    for jf in files:
        try: posts += source_mediacrawler_weibo(str(jf))
        except Exception: continue
    if not posts: _login_or_no_result("wb", blob)
    return posts

def source_x(path):
    rows = json.load(open(path, encoding="utf-8"))
    if isinstance(rows, dict): rows = rows.get("data", [rows])
    return [normalize("x", "@"+str(t.get("username","")), "", t.get("text",""),
            (t.get("date","") or "")[:10], t.get("url",""),
            {"likes": t.get("likes"), "retweets": t.get("retweets"),
             "replies": t.get("replies"), "views": t.get("views")}, "twscrape") for t in rows]

def source_manual():
    plat = input("平台(reddit/xiaohongshu/x): ").strip() or "manual"
    text = sys.stdin.read().strip()
    return [normalize(plat, "manual", "", text, "", "", {}, "manual")]

def save_to_ingestion(posts, pid):
    import pathlib
    root = pathlib.Path(os.environ.get("PM_AGENT_PROJECT_DIR") or f"projects/{pid}")
    d = root / "ingestion"; d.mkdir(parents=True, exist_ok=True)
    f = d / "social-posts.jsonl"
    seen = set()
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try: seen.add(json.loads(line)["id"])
            except Exception: pass
    added = 0
    with f.open("a", encoding="utf-8") as fh:
        for p in posts:
            if p["id"] in seen: continue
            fh.write(json.dumps(p, ensure_ascii=False) + "\n"); added += 1
    return str(f), added, len(posts) - added

def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    src = sys.argv[1]
    if src == "reddit":
        q = sys.argv[2]; limit = int(sys.argv[sys.argv.index("--limit")+1]) if "--limit" in sys.argv else 8
        posts = source_reddit(q, limit)
    elif src == "mediacrawler":
        posts = source_mediacrawler(sys.argv[2])
    elif src == "xhs-live":
        q = sys.argv[2]; limit = int(sys.argv[sys.argv.index("--limit")+1]) if "--limit" in sys.argv else 15
        posts = source_xhs_live(q, limit)
    elif src == "wb-live":
        q = sys.argv[2]; limit = int(sys.argv[sys.argv.index("--limit")+1]) if "--limit" in sys.argv else 15
        posts = source_wb_live(q, limit)
    elif src == "x":
        posts = source_x(sys.argv[2])
    elif src == "manual":
        posts = source_manual()
    else:
        print("未知源:", src); return
    if "--project" in sys.argv:
        pid = sys.argv[sys.argv.index("--project")+1]
        f, added, dup = save_to_ingestion(posts, pid)
        print(f"✓ 已写入 {f}：新增 {added}，去重 {dup}", file=sys.stderr)
    print(json.dumps(posts, ensure_ascii=False))

if __name__ == "__main__":
    main()

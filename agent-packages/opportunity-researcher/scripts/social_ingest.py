#!/usr/bin/env python3
"""
社媒帖子采集 → 归一 → 喂 opportunity-researcher。采集与 agent 解耦。
用法：
  python3 social_ingest.py reddit "kpop parasocial" --limit 8
  python3 social_ingest.py mediacrawler <导出.json>
  python3 social_ingest.py x <twscrape导出.json>
  python3 social_ingest.py manual
不带 --project 时把归一后的 JSON 打到 stdout（供引擎读取）；带 --project 落盘去重。
Token：读 PM_WORKBENCH_API_KEY 或 ~/.config/pm-workbench/tavily-api-key。
"""
import sys, os, json, ssl, hashlib, datetime, urllib.request

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

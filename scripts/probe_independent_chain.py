# -*- coding: utf-8 -*-
"""独立站完整链路取证 + 发文表单字段抓取（只读）。
用当前账号有权限的站点，走 控制中心 → token → 站点 session → 读取表单/栏目。
额外：抓取 /article/form 的 HTML 表单字段，作为发文接口文档的一手依据。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests
from app_paths import data_dir

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

cfg = {}
for p in (data_dir() / "config.json", ROOT / "config.json"):
    if p.exists():
        cfg = json.loads(p.read_text(encoding="utf-8"))
        break

username = cfg.get("username") or ""
password = cfg.get("password") or ""
admin_url = (cfg.get("admin_url") or "https://center-admin.ruli.com").rstrip("/")
api_url = admin_url.replace("-admin.", "-admin-api.", 1)

s = requests.Session()
s.headers.update({"User-Agent": UA, "Content-Type": "application/json",
                  "Accept": "application/json, text/plain, */*"})
tok = s.post(f"{api_url}/login/password-login",
             json={"username": username, "password": password, "remember": True},
             timeout=20).json()["data"]["token"]
H = {"Authorization": f"Bearer {tok}"}

apps = s.get(f"{api_url}/site/apps", params={"page": 1, "limit": 300},
             headers=H, timeout=20).json()["data"]["items"]
real = [a for a in apps if str(a.get("categoryText") or "").strip() != "内部系统"]
print(f"可见应用 {len(apps)}，过滤内部系统后 {len(real)}")

# 选 2 个独立站（admin. 非 ruli.com）+ 那个合作站
indep = [a for a in real if a["url"].split("://")[1].split("/")[0].startswith("admin.")
         and "ruli.com" not in a["url"]]
coop = [a for a in real if "hz-admin-" in a["url"]]
pick = indep[:3] + coop[:1]
print("取样:", [a["signature"] for a in pick])

out = {"app_total": len(apps), "app_after_filter": len(real), "sites": []}

for a in pick:
    sig, name, cms_url = a["signature"], a["name"], a["url"]
    rec = {"signature": sig, "name": name, "cms_url": cms_url,
           "categoryText": a.get("categoryText")}
    print(f"\n===== {sig} ({name}) {cms_url}")

    rt = s.post(f"{api_url}/site/app-create-access-token", json={"app": sig},
                headers=H, timeout=20).json()
    rec["token_api"] = {"code": rt.get("code"), "message": rt.get("message")}
    data = rt.get("data") or {}
    t = data.get("token")
    tv = t.get("name") if isinstance(t, dict) else t
    if not tv:
        print("  换token失败:", rt.get("message"))
        out["sites"].append(rec)
        continue
    rec["token_api"]["expire_at"] = (t or {}).get("expire_at") if isinstance(t, dict) else None

    site = requests.Session()
    site.headers.update({"User-Agent": UA,
                         "Accept": "text/html,application/xhtml+xml,application/json,*/*"})
    rr = site.get(f"{cms_url}?token={tv}", timeout=20, allow_redirects=True)
    rec["token_nav"] = {"status": rr.status_code, "final_url": rr.url[:110],
                        "cookies": sorted({c.name for c in site.cookies}),
                        "is_login_page": "name=\"password\"" in (rr.text or "")
                        or 'type="password"' in (rr.text or "")}
    print("  token导航:", rec["token_nav"])

    base = cms_url.replace("/login", "").rstrip("/")

    # 栏目接口
    rc = site.get(f"{base}/article/category-tree", timeout=20)
    try:
        cj = rc.json()
        rec["category_tree"] = {"status": rc.status_code, "code": cj.get("code"),
                                "count": len(cj.get("data") or []),
                                "sample": (cj.get("data") or [])[:4]}
    except Exception:
        rec["category_tree"] = {"status": rc.status_code, "body_head": (rc.text or "")[:150]}
    print("  栏目:", json.dumps(rec["category_tree"], ensure_ascii=False)[:260])

    # 文章列表接口（读取列表，验证会话有效）
    rl = site.get(f"{base}/article/index",
                  params={"page": 1, "limit": 5}, timeout=20)
    try:
        lj = rl.json()
        rec["article_index"] = {"status": rl.status_code, "code": lj.get("code"),
                                "total": (lj.get("data") or {}).get("total"),
                                "sample_keys": list(((lj.get("data") or {}).get("items") or [{}])[0].keys())[:25]}
    except Exception:
        rec["article_index"] = {"status": rl.status_code, "body_len": len(rl.text or "")}
    print("  列表:", json.dumps(rec["article_index"], ensure_ascii=False)[:300])

    # 发文表单页 → 解析字段
    rf = site.get(f"{base}/article/form", timeout=20)
    html = rf.text or ""
    fields = []
    for m in re.finditer(r"<(input|textarea|select)\b([^>]*)>", html, re.I):
        tag, attrs = m.group(1).lower(), m.group(2)
        d = dict(re.findall(r'([a-zA-Z\-]+)\s*=\s*"([^"]*)"', attrs))
        if d.get("name") or d.get("id"):
            fields.append({"tag": tag, "name": d.get("name") or d.get("id"),
                           "type": d.get("type", "" if tag == "input" else tag),
                           "placeholder": d.get("placeholder", "")[:40]})
    rec["form_page"] = {"status": rf.status_code, "title": (html.split("<title>")[1].split("</title>")[0].strip() if "<title>" in html else ""),
                        "has_editor": "ueditor" in html.lower() or "editor" in html.lower(),
                        "fields": fields[:30]}
    print("  表单:", rec["form_page"]["title"], "字段:", [f["name"] for f in fields[:18]])

    out["sites"].append(rec)

Path("scripts/independent_chain_result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写出 scripts/independent_chain_result.json")

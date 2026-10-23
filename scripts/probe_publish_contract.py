# -*- coding: utf-8 -*-
"""端点契约探测（零写入）：
- 只用 GET / HEAD / OPTIONS 探测端点存在性与允许的方法；
- 绝不 POST 任何业务数据到发文接口（避免误建文章）。
发文接口的参数契约由站点前端 JS 源码确定（见 scripts/article_form_inline.js）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests
from app_paths import data_dir

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
cfg = json.loads((data_dir() / "config.json").read_text(encoding="utf-8"))
admin_url = (cfg.get("admin_url") or "https://center-admin.ruli.com").rstrip("/")
api_url = admin_url.replace("-admin.", "-admin-api.", 1)

s = requests.Session()
s.headers.update({"User-Agent": UA, "Content-Type": "application/json"})
ctrl = s.post(f"{api_url}/login/password-login",
              json={"username": cfg["username"], "password": cfg["password"], "remember": True},
              timeout=20).json()["data"]["token"]
H = {"Authorization": f"Bearer {ctrl}"}
out = {}


def site_session(sig):
    rt = s.post(f"{api_url}/site/app-create-access-token", json={"app": sig}, headers=H, timeout=20).json()
    if rt.get("code") != 0:
        return None, rt
    tv = rt["data"]["token"]["name"]
    base = rt["data"]["url"].replace("/login", "").rstrip("/")
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})
    sess.get(f"{base}/login?token={tv}", timeout=20)
    return sess, {"base": base, "token_len": len(tv)}


ENDPOINTS = ["/article/form", "/article/index", "/article/category-tree",
             "/common/article-categorys", "/site/upload", "/site/user-info",
             "/site/logout", "/article/delete", "/article/del"]

# ---- 独立站 ----
sess, info = site_session("cengguai")
print("独立站 cengguai:", info)
out["cengguai"] = {"info": info, "endpoints": {}}
if sess:
    base = info["base"]
    for ep in ENDPOINTS:
        rec = {}
        try:
            r = sess.get(base + ep, timeout=15)
            rec["GET"] = {"status": r.status_code, "ct": r.headers.get("Content-Type", ""),
                          "len": len(r.text or ""), "head": (r.text or "")[:130]}
        except Exception as e:
            rec["GET"] = {"error": str(e)[:90]}
        try:
            r = sess.options(base + ep, timeout=15,
                             headers={"Origin": base, "Access-Control-Request-Method": "POST"})
            rec["OPTIONS"] = {"status": r.status_code, "allow": r.headers.get("Allow", ""),
                              "access_control": r.headers.get("Access-Control-Allow-Methods", "")}
        except Exception as e:
            rec["OPTIONS"] = {"error": str(e)[:90]}
        out["cengguai"]["endpoints"][ep] = rec
        print(f"  {ep:28s} GET={rec.get('GET',{}).get('status')} "
              f"ct={str(rec.get('GET',{}).get('ct'))[:30]} "
              f"OPTIONS={rec.get('OPTIONS',{}).get('status')} allow={rec.get('OPTIONS',{}).get('allow','')}")

# ---- aicms ----
print("\naicms:")
rt = s.post(f"{api_url}/site/app-create-access-token", json={"app": "aicms"}, headers=H, timeout=20).json()
data = rt.get("data") or {}
tv = (data.get("token") or {}).get("name")
out["aicms"] = {"token_api": {"code": rt.get("code"), "message": rt.get("message"),
                              "url": data.get("url"),
                              "expire": (data.get("token") or {}).get("expire_at")},
                "endpoints": {}}
print("  换token:", json.dumps(out["aicms"]["token_api"], ensure_ascii=False))

for api_base in ("https://aicms-admin-api.ruli.com", "https://aicms-admin.ruli.com"):
    for ep in ("/site/take-new-token", "/site/user-info", "/site/dashboard",
               "/article/index", "/article/category-tree", "/article/form"):
        rec = {}
        for m in ("GET", "OPTIONS"):
            try:
                if m == "GET":
                    r = requests.get(api_base + ep, timeout=12,
                                     headers={"User-Agent": UA, "Authorization": f"Bearer {tv or ''}",
                                              "Origin": "https://aicms-admin.ruli.com",
                                              "Referer": "https://aicms-admin.ruli.com/"})
                else:
                    r = requests.options(api_base + ep, timeout=12,
                                         headers={"User-Agent": UA,
                                                  "Origin": "https://aicms-admin.ruli.com",
                                                  "Access-Control-Request-Method": "POST"})
                rec[m] = {"status": r.status_code, "ct": r.headers.get("Content-Type", ""),
                          "allow": r.headers.get("Allow", ""),
                          "head": (r.text or "")[:140]}
            except Exception as e:
                rec[m] = {"error": str(e)[:80]}
        out["aicms"]["endpoints"][api_base + ep] = rec
        g, o = rec.get("GET", {}), rec.get("OPTIONS", {})
        print(f"  {api_base.replace('https://','')}{ep:26s} GET={g.get('status')} "
              f"allow={o.get('allow','')} head={str(g.get('head'))[:70]!r}")

Path("scripts/endpoint_probe.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写出 scripts/endpoint_probe.json")

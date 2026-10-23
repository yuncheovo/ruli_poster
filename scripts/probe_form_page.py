# -*- coding: utf-8 -*-
"""抓取发文表单页原始 HTML + 提交接口调用方式（只读）。"""
import json
import re
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
tok = s.post(f"{api_url}/login/password-login",
             json={"username": cfg["username"], "password": cfg["password"], "remember": True},
             timeout=20).json()["data"]["token"]
H = {"Authorization": f"Bearer {tok}"}

SIG = "cengguai"
cms_url = "https://admin.cengguai.com/login"
rt = s.post(f"{api_url}/site/app-create-access-token", json={"app": SIG}, headers=H, timeout=20).json()
tv = rt["data"]["token"]["name"]

site = requests.Session()
site.headers.update({"User-Agent": UA,
                     "Accept": "text/html,application/xhtml+xml,application/json,*/*",
                     "Referer": "https://admin.cengguai.com/"})
site.get(f"{cms_url}?token={tv}", timeout=20)

base = "https://admin.cengguai.com"
out = {}

for ep in ("/article/form", "/article/index"):
    r = site.get(base + ep, timeout=20)
    out[ep] = {"status": r.status_code, "len": len(r.text or ""), "html": (r.text or "")}
    fn = "scripts/form_page.html" if "form" in ep else "scripts/index_page.html"
    Path(fn).write_text(r.text or "", encoding="utf-8")
    print(f"{ep} -> {r.status_code} len={len(r.text or '')}  -> {fn}")

# 从表单页提取：表单字段、JS 中的提交地址、编辑器类型
html = out["/article/form"]["html"]
print("\n--- 表单页关键片段 ---")
for kw in ("action=", "ueditor", "layui", "editor", "ajax", "post(", "/article/", "name=\"", "upload"):
    idx = html.lower().find(kw.lower())
    if idx >= 0:
        print(f"[{kw}] ...{html[max(0,idx-90):idx+170]}...".replace("\n", " ")[:330])

Path("scripts/form_scrape.json").write_text(json.dumps(
    {k: {kk: vv for kk, vv in v.items() if kk != "html"} for k, v in out.items()},
    ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写出 scripts/form_page.html / index_page.html")

# -*- coding: utf-8 -*-
"""真实链路只读取证：控制中心登录 → 一键登录换 token → 站点接口可用性。
安全约定：
- 凭据由脚本自行从配置读取，不打印、不外传；
- 全程只做 GET / 表单页面读取，绝不提交任何业务数据（不发文章、不改数据）。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests
from app_paths import data_dir

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# ---- 读配置（不打印凭据）----
cfg = {}
for p in (data_dir() / "config.json", ROOT / "config.json"):
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            cfg["_from"] = str(p)
            break
        except Exception:
            continue

username = cfg.get("username") or cfg.get("user") or ""
password = cfg.get("password") or cfg.get("pwd") or ""
admin_url = (cfg.get("admin_url") or "https://center-admin.ruli.com").rstrip("/")

print(f"[cfg] source={cfg.get('_from')}")
print(f"[cfg] username_present={bool(username)} password_present={bool(password)} admin_url={admin_url}")
if not (username and password):
    print("[!] 配置中缺少账号或密码，退出")
    sys.exit(1)

api_url = admin_url.replace("-admin.", "-admin-api.", 1) if "-admin." in admin_url else admin_url
print(f"[cfg] api_url={api_url}")

s = requests.Session()
s.headers.update({"User-Agent": UA, "Content-Type": "application/json",
                  "Accept": "application/json, text/plain, */*"})

report = {"steps": []}


def step(name, **kw):
    kw["step"] = name
    report["steps"].append(kw)
    print(f"[{name}] " + json.dumps({k: v for k, v in kw.items() if k != "step"},
                                   ensure_ascii=False)[:400])


# ---- 1. 控制中心登录 ----
r = s.post(f"{api_url}/login/password-login",
           json={"username": username, "password": password, "remember": True}, timeout=20)
d = r.json()
ctrl_token = (d.get("data") or {}).get("token")
step("ctrl_login", status=r.status_code, code=d.get("code"),
     message=d.get("message"), token_len=len(ctrl_token or ""),
     expire=(d.get("data") or {}).get("expire_at"))
if not ctrl_token:
    print("[!] 控制中心登录失败，退出")
    sys.exit(1)

H = {"Authorization": f"Bearer {ctrl_token}"}

# ---- 2. 站点列表 ----
r = s.get(f"{api_url}/site/apps", params={"page": 1, "limit": 300}, headers=H, timeout=20)
apps = (r.json().get("data") or {}).get("items", [])
real = [a for a in apps if str(a.get("categoryText") or "").strip() != "内部系统"]
step("apps", total=r.json().get("data", {}).get("total"),
     all_items=len(apps), after_filter=len(real))
print("     站点样例:", json.dumps(real[:3], ensure_ascii=False)[:400])

# ---- 3. 一键登录换 token（抽样三类各一个）----
samples = [("independent", "nouhua"), ("cooperation", "yeekang"), ("aicms", "aicms")]
for kind, sig in samples:
    r = s.post(f"{api_url}/site/app-create-access-token", json={"app": sig}, headers=H, timeout=20)
    d = r.json()
    data = d.get("data") or {}
    tok = data.get("token")
    token_val = tok.get("name") if isinstance(tok, dict) else tok
    cms_url = data.get("url", "")
    step("get_token:" + sig, kind=kind, http=r.status_code, code=d.get("code"),
         message=d.get("message"), cms_url=cms_url,
         token_present=bool(token_val), token_len=len(str(token_val or "")),
         token_expire=(tok or {}).get("expire_at") if isinstance(tok, dict) else None)

    if not token_val:
        continue

    # ---- 4. 用 token 导航换取站点会话（只读）----
    site = requests.Session()
    site.headers.update({"User-Agent": UA, "Accept": "*/*"})
    try:
        rr = site.get(f"{cms_url}?token={token_val}", timeout=20, allow_redirects=True)
        cookie_names = sorted({c.name for c in site.cookies})
        step("token_nav:" + sig, status=rr.status_code, final_url=rr.url[:100],
             cookies=cookie_names,
             body_len=len(rr.text or ""),
             body_head=(rr.text or "")[:80])
    except Exception as e:
        step("token_nav:" + sig, error=str(e)[:120])
        continue

    # ---- 5. 会话内访问栏目 / 发文表单页（只读）----
    base = cms_url.replace("/login", "").rstrip("/")
    for ep, method in (("/article/category-tree", "get"), ("/article/form", "get"),
                       ("/site/user-info", "get")):
        try:
            if method == "get":
                rr = site.get(f"{base}{ep}", timeout=20)
            txt = (rr.text or "")
            head = txt[:200]
            step(f"api:{sig}{ep}", status=rr.status_code,
                 ct=rr.headers.get("Content-Type", ""), len=len(txt),
                 head=head)
        except Exception as e:
            step(f"api:{sig}{ep}", error=str(e)[:110])

Path("scripts").mkdir(exist_ok=True)
Path("scripts/real_chain_result.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写出 scripts/real_chain_result.json")

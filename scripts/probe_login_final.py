# -*- coding: utf-8 -*-
"""终极验证：穷举 Content-Type / Header / 来源组合，确认独立站密码登录入口是否完全关闭。
判据：若任何组合能返回「验证码错误/密码错误」类业务错误，说明入口可用；
      若一律返回「登录入口错误」，说明服务端在业务校验前即拒绝（入口关闭）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
BASE = "https://admin.cengguai.com"
CREDS = {"username": "13000000000", "password": "Wrong!123", "captcha": "0000", "remember": True}

COMBOS = [
    ("json + XHR + referer", "json", {"X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/login", "Origin": BASE}),
    ("json 裸请求", "json", {}),
    ("form + XHR + referer", "form", {"X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/login", "Origin": BASE}),
    ("form 裸请求", "form", {}),
    ("json + 伪装控制中心 referer", "json", {"Referer": "https://center-admin.ruli.com/go/app", "Origin": "https://center-admin.ruli.com"}),
    ("json + X-CSRF-Token 空", "json", {"X-CSRF-Token": "", "X-Requested-With": "XMLHttpRequest"}),
    ("json + Content-Type form 但 JSON body", "raw-json-as-form", {"X-Requested-With": "XMLHttpRequest"}),
]

out = []
for name, mode, hdr in COMBOS:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})
    s.get(f"{BASE}/login", timeout=12)
    s.get(f"{BASE}/login/captcha", timeout=12)
    headers = dict(hdr)
    try:
        if mode == "json":
            headers["Content-Type"] = "application/json"
            r = s.post(f"{BASE}/login", json=CREDS, headers=headers, timeout=15)
        elif mode == "form":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            r = s.post(f"{BASE}/login", data=CREDS, headers=headers, timeout=15)
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            r = s.post(f"{BASE}/login", data=json.dumps(CREDS), headers=headers, timeout=15)
        rec = {"combo": name, "status": r.status_code, "body": (r.text or "")[:180]}
    except Exception as e:
        rec = {"combo": name, "error": str(e)[:110]}
    out.append(rec)
    print(f"{name:38s} -> {rec.get('status')} {str(rec.get('body', rec.get('error')))[:120]}")

# 对照：aicms 用同样方式（已知接口存在），验证方法有效性
print("\n[对照组] aicms /login/password-login:")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Content-Type": "application/json",
                  "Referer": "https://aicms-admin.ruli.com/",
                  "Origin": "https://aicms-admin.ruli.com"})
r = s.post("https://aicms-admin-api.ruli.com/login/password-login",
           json={"username": "13000000000", "password": "Wrong!123", "verify": "0000", "remember": True},
           timeout=15)
ctl = {"status": r.status_code, "body": (r.text or "")[:200]}
print("  ->", ctl["status"], ctl["body"])
out.append({"combo": "aicms 对照", **ctl})

Path("scripts/login_matrix_final.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写出 scripts/login_matrix_final.json")

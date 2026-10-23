# -*- coding: utf-8 -*-
"""登录端点穷举（用无效凭据，仅观察服务端响应差异，确认是否存在可用的独立登录入口）。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
BASE = "https://admin.cengguai.com"

CANDIDATES = [
    ("/login", {"username": "13000000000", "password": "Wrong!123", "captcha": "0000", "remember": True}),
    ("/login/password-login", {"username": "13000000000", "password": "Wrong!123", "verify": "0000", "remember": True}),
    ("/login/password-login", {"username": "13000000000", "password": "Wrong!123", "captcha": "0000", "remember": True}),
    ("/login/verify", {"username": "13000000000", "password": "Wrong!123", "captcha": "0000"}),
    ("/login/check", {"username": "13000000000", "password": "Wrong!123", "captcha": "0000"}),
    ("/login/do", {"username": "13000000000", "password": "Wrong!123", "captcha": "0000"}),
    ("/login/submit", {"username": "13000000000", "password": "Wrong!123", "captcha": "0000"}),
    ("/site/login", {"username": "13000000000", "password": "Wrong!123", "captcha": "0000"}),
    ("/api/login", {"username": "13000000000", "password": "Wrong!123", "captcha": "0000"}),
    ("/user/login", {"username": "13000000000", "password": "Wrong!123", "captcha": "0000"}),
]

out = []
for path, payload in CANDIDATES:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA, "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/login", "Origin": BASE,
    })
    s.get(f"{BASE}/login", timeout=12)
    s.get(f"{BASE}/login/captcha", timeout=12)  # 取 SESSID
    try:
        r = s.post(f"{BASE}{path}", json=payload, timeout=15)
        rec = {"path": path, "status": r.status_code,
               "ct": r.headers.get("Content-Type", ""),
               "body": (r.text or "")[:220]}
    except Exception as e:
        rec = {"path": path, "error": str(e)[:110]}
    out.append(rec)
    print(f"{path:26s} -> {rec.get('status')} {str(rec.get('body', rec.get('error')))[:150]}")

Path("scripts/login_endpoints.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写出 scripts/login_endpoints.json")

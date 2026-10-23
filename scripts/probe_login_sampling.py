# -*- coding: utf-8 -*-
"""批量抽样：验证「站点侧密码登录入口一律关闭」的普遍性（统计证据）。
仅提交无效凭据，不含任何真实账号密码。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import requests
from app_paths import data_dir

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FAKE = {"username": "13000000000", "password": "Wrong!123", "captcha": "0000", "remember": True}

cfg = json.loads((data_dir() / "config.json").read_text(encoding="utf-8"))
admin_url = (cfg.get("admin_url") or "https://center-admin.ruli.com").rstrip("/")
api_url = admin_url.replace("-admin.", "-admin-api.", 1)

s = requests.Session()
s.headers.update({"User-Agent": UA, "Content-Type": "application/json"})
ctrl = s.post(f"{api_url}/login/password-login",
              json={"username": cfg["username"], "password": cfg["password"], "remember": True},
              timeout=20).json()["data"]["token"]
H = {"Authorization": f"Bearer {ctrl}"}

apps = s.get(f"{api_url}/site/apps", params={"page": 1, "limit": 300},
             headers=H, timeout=20).json()["data"]["items"]
real = [a for a in apps if str(a.get("categoryText") or "").strip() != "内部系统"]
print(f"可见应用 {len(real)} 个，抽样 25 个独立站验证登录入口\n")

stats = {"登录入口错误": 0, "其他": 0, "连接失败": 0}
details = []
for a in real[:25]:
    base = a["url"].replace("/login", "").rstrip("/")
    dom = base.split("://")[1].split("/")[0]
    if dom.startswith("hz-admin-") or "ruli.com" in dom:
        continue
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Content-Type": "application/json",
                         "X-Requested-With": "XMLHttpRequest",
                         "Referer": f"{base}/login", "Origin": base})
    try:
        sess.get(f"{base}/login", timeout=10)
        sess.get(f"{base}/login/captcha", timeout=10)
        r = sess.post(f"{base}/login", json=FAKE, timeout=12)
        body = (r.text or "")[:120]
        if "登录入口错误" in body:
            stats["登录入口错误"] += 1
            tag = "入口关闭"
        else:
            stats["其他"] += 1
            tag = "★其他"
        # token 通道
        rt = sess.get(f"{base}/login?token=INVALID", timeout=10)
        token_msg = (rt.text or "")[:30]
        details.append({"sig": a["signature"], "name": a["name"], "domain": dom,
                        "post_login": body, "tag": tag, "token_channel": token_msg})
        print(f"  {a['signature']:12s} {dom:26s} {tag:6s} {body[:60]}")
    except Exception as e:
        stats["连接失败"] += 1
        details.append({"sig": a["signature"], "domain": dom, "error": str(e)[:80]})
        print(f"  {a['signature']:12s} {dom:26s} 连接失败 {str(e)[:50]}")

print(f"\n统计: {stats}")
Path("scripts/login_sampling.json").write_text(
    json.dumps({"stats": stats, "details": details}, ensure_ascii=False, indent=2), encoding="utf-8")
print("已写出 scripts/login_sampling.json")

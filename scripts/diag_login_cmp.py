# -*- coding: utf-8 -*-
"""对比测试：工具自己的 login_cms / login_cms_browser / token 路径，对失败站分别跑一遍。"""
import json, sys
from pathlib import Path
HOME = Path.home() / "ruli_poster"
cfg = json.load(open(HOME / "config.json", encoding="utf-8"))
user = cfg.get("username") or cfg.get("ctrl_user")
pwd = cfg.get("password") or cfg.get("ctrl_pwd")
admin_url = cfg.get("admin_url", "https://center-admin.ruli.com")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ruli_core import RuliClient

TARGETS = {"普伽美": "cp-gas", "宜康网合作站": "yeekang", "宜康网合作站zxmr": "yeekang-zxmr"}

cli = RuliClient(user, pwd, admin_url=admin_url)
print("[ctrl] 登录:", cli.login_ctrl())
cli.get_apps()
for nm, sig in TARGETS.items():
    print("\n" + "="*64)
    print(f"{nm}  (sig={sig})")
    app = cli.apps_map.get(sig, {})
    url = app.get("url", "")
    dom = url.split("://")[1].split("/")[0] if "://" in url else ""
    is_coop = dom.startswith("hz-admin-")
    is_indep = (dom.startswith("admin.") and "ruli.com" not in dom) or is_coop
    is_aicms = "ruli.com" in dom and not is_coop
    print(f"  url={url}")
    print(f"  判定: 合作站={is_coop} 独立站={is_indep} aicms={is_aicms}")

    # 1) token 接口
    ad = cli.get_app_token(sig)
    print("  [1] get_app_token:", "OK" if ad else "FAIL(NULL)")

    # 2) token 直导（_login_cms_via_token）
    try:
        r2 = cli._login_cms_via_token(sig)
        print("  [2] _login_cms_via_token:", "OK" if r2 else "FAIL(NULL)",
              "| cookies:", len(r2.get("cookies", {})) if r2 else 0,
              "| api_base:", (r2 or {}).get("api_base"))
    except Exception as e:
        print("  [2] _login_cms_via_token 异常:", e)

    # 3) 浏览器一键登录（login_cms_browser）
    try:
        r3 = cli.login_cms_browser(sig)
        print("  [3] login_cms_browser:", "OK" if r3 else "FAIL(NULL)",
              "| cookies:", len((r3 or {}).get("cookies", {})),
              "| api_base:", (r3 or {}).get("api_base"))
    except Exception as e:
        print("  [3] login_cms_browser 异常:", type(e).__name__, e)

    # 4) 完整 login_cms（GUI 发布实际调用的入口）
    try:
        r4 = cli.login_cms(sig)
        print("  [4] login_cms(最终):", "OK" if r4 else "FAIL(NULL)",
              "| auth_type:", (r4 or {}).get("auth_type"),
              "| cookies:", len((r4 or {}).get("cookies", {})),
              "| api_base:", (r4 or {}).get("api_base"))
    except Exception as e:
        print("  [4] login_cms 异常:", type(e).__name__, e)

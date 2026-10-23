# -*- coding: utf-8 -*-
"""诊断：在已登录控制中心的浏览器里，真实点击站点“登录”按钮，
抓取弹窗/跳转实际发出的请求与最终 cookie，定位工具为何登录不上。
不打印任何凭据。"""
import asyncio, json, sys
from pathlib import Path

HOME = Path.home() / "ruli_poster"
cfg = json.load(open(HOME / "config.json", encoding="utf-8"))
user = cfg.get("username") or cfg.get("ctrl_user")
pwd = cfg.get("password") or cfg.get("ctrl_pwd")
admin_url = cfg.get("admin_url", "https://center-admin.ruli.com")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ruli_core import RuliClient

TARGETS = ["普伽美", "宜康网合作站", "宜康网合作站zxmr"]

async def main():
    cli = RuliClient(user, pwd, admin_url=admin_url)
    if not cli.login_ctrl():
        print("[FAIL] 控制中心登录失败"); return
    apps = cli.get_apps()
    name_sig = {}
    for a in apps:
        name_sig[a.get("name", "")] = a.get("signature")
    print("[i] 应用数:", len(apps))
    found = {}
    for t in TARGETS:
        hit = [n for n in name_sig if t in n]
        for n in hit:
            found[n] = name_sig[n]
    print("[i] 命中目标:", found)

    from playwright.async_api import async_playwright
    from ruli_core import launch_chromium
    async with async_playwright() as p:
        browser = await launch_chromium(p, headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = await ctx.new_page()
        # 真实表单登录控制中心（与工具 _login_ctrl 一致）
        await page.goto(f"{cli.admin_url}/login", wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        try:
            await page.fill('input[placeholder*="手机"]', user)
            await page.fill('input[type="password"]', pwd)
            await page.click('button:has-text("登录")')
        except Exception as e:
            print("[!] 填写/点击登录失败:", e)
        await page.wait_for_timeout(3000)
        print("[diag] 登录后URL:", page.url)
        # 进入应用管理页
        await page.goto(f"{cli.admin_url}/go/app", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        print("[diag] /go/app URL:", page.url)
        body = await page.inner_text("body")
        print("[diag] body文字片段:", body[:200].replace("\n"," | "))
        try:
            await page.wait_for_selector('.el-table__body tr.el-table__row', timeout=12000)
        except Exception as e:
            print("[!] 表格未渲染:", e)
            await browser.close(); return

        for name, sig in found.items():
            print("\n" + "="*60)
            print(f"站点: {name}  (sig={sig})")
            app = cli.apps_map.get(sig, {})
            print("  app.url =", app.get("url"), "| domain含ruli.com:", "ruli.com" in app.get("url",""))
            # 直接用 API 取 token 响应（与工具 get_app_token 一致）
            resp = cli.session.post(
                f"{cli.api_url}/site/app-create-access-token",
                json={"app": sig}, headers=cli._auth_header(), timeout=15)
            try:
                j = resp.json()
            except Exception:
                j = {}
            print("  [API] app-create-access-token 状态码:", resp.status_code,
                  "| code:", j.get("code"), "| msg:", str(j.get("message"))[:80])
            print("  [API] data keys:", list(j.get("data", {}).keys()) if isinstance(j.get("data"), dict) else j.get("data"))
            if j.get("code") == 0 and isinstance(j.get("data"), dict):
                tk = j["data"].get("token")
                tname = tk.get("name") if isinstance(tk, dict) else tk
                print("  [API] token.name =", tname, "| expire_at =", (tk.get("expire_at") if isinstance(tk, dict) else ""))
                # 用该 token 直接导航 CMS，看是否能拿到 cookie
                cms_url = j["data"].get("url","")
                nav = await ctx.new_page()
                await nav.goto(f"{cms_url}?token={tname}", wait_until="domcontentloaded", timeout=15000)
                await nav.wait_for_timeout(4000)
                cookies = await ctx.cookies()
                dom = nav.url.split("://")[1].split("/")[0] if "://" in nav.url else ""
                sc = {c["name"]: c["value"] for c in cookies
                      if dom and (dom in c.get("domain","") or c.get("domain","") in dom)}
                print("  [nav] CMS最终URL:", nav.url[:120])
                print("  [nav] 拿到站点cookie数:", len(sc), list(sc.keys())[:8])
                await nav.close()
            # 再用网页按钮点一次，捕获弹窗实际行为
            reqlog = []
            async def on_req(r):
                u = r.url
                if any(k in u for k in ["token","access","login","site","app"]):
                    try:
                        body = r.post_data
                    except Exception:
                        body = None
                    reqlog.append((u, r.method, body))
            page.on("request", on_req)
            clicked = await page.evaluate(f"""
                () => {{
                    const name = {json.dumps(name)};
                    for (let row of document.querySelectorAll('.el-table__body tr.el-table__row')) {{
                        if (row.textContent.includes(name)) {{
                            const link = row.querySelector('a.el-link--warning')
                                || [...row.querySelectorAll('a,button')].find(e=>/登录|一键|打开/.test(e.textContent));
                            if (link) {{ link.click(); return true; }}
                        }}
                    }}
                    return false;
                }}""")
            print("  [web] 点击登录链接:", clicked)
            newpage = None
            try:
                newpage = await page.wait_for_event("page", timeout=12000)
                await newpage.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                newpage = None
            target = newpage if newpage else page
            await target.wait_for_timeout(4000)
            print("  [web] 最终URL:", target.url[:120])
            cookies = await ctx.cookies()
            dom = target.url.split("://")[1].split("/")[0] if "://" in target.url else ""
            sc = {c["name"]: c["value"] for c in cookies
                  if dom and (dom in c.get("domain","") or c.get("domain","") in dom)}
            print("  [web] 拿到站点cookie数:", len(sc), list(sc.keys())[:8])
            print("  [web] 该过程请求:", [(u[:90], m, (b[:80] if b else "")) for u,m,b in reqlog[-8:]])
            page.remove_listener("request", on_req)
            try:
                if newpage: await newpage.close()
            except Exception:
                pass
        await browser.close()

asyncio.run(main())

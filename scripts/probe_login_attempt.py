# -*- coding: utf-8 -*-
"""决定性实验：在真实浏览器中完成登录流程（用无效凭据），观察服务端返回。
目的：区分「服务端硬守卫」与「协议/指纹缺失」导致的失败。
注意：使用随机无效账号，不会影响任何真实账号。
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FAKE_USER = "13000000000"
FAKE_PWD = "WrongPass!123"
FAKE_CAP = "0000"


async def main():
    from playwright.async_api import async_playwright
    from ruli_core import launch_chromium

    targets = [("independent", "https://admin.cengguai.com"),
               ("cooperation", "https://hz-admin-yeekang.ruli.com")]
    out = {}
    async with async_playwright() as p:
        b = await launch_chromium(p, headless=True)
        for kind, base in targets:
            ctx = await b.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
            pg = await ctx.new_page()
            log = []
            pg.on("response", lambda r: log.append({"url": r.url, "status": r.status})
                  if "/login" in r.url else None)
            res = {"kind": kind, "base": base}
            try:
                await pg.goto(f"{base}/login", wait_until="domcontentloaded", timeout=25000)
                await pg.wait_for_timeout(2000)
                await pg.fill('input[name="username"]', FAKE_USER)
                await pg.fill('input[name="password"]', FAKE_PWD)
                await pg.fill('input[name="captcha"]', FAKE_CAP)

                # 监听 /login 的响应体
                body_holder = {}

                async def on_resp(r):
                    if r.url.rstrip("/").endswith("/login") or "/login?" in r.url:
                        try:
                            body_holder["body"] = (await r.text())[:400]
                            body_holder["status"] = r.status
                            body_holder["ct"] = r.headers.get("content-type", "")
                        except Exception:
                            pass
                pg.on("response", lambda r: asyncio.create_task(on_resp(r)))

                await pg.click('button[lay-submit], button:has-text("登"), .layui-btn')
                await pg.wait_for_timeout(3500)
                res["login_response"] = body_holder
                res["url_after"] = pg.url
                res["has_pwd_after"] = await pg.evaluate("()=>!!document.querySelector('input[type=password]')")
                res["msg_text"] = await pg.evaluate(
                    "()=>{const e=document.querySelector('.layui-layer-content,.el-message,.layui-layer-msg');return e?e.innerText.trim().slice(0,200):''}")
                print(f"\n===== {kind} {base}")
                print("  点击登录后响应:", json.dumps(body_holder, ensure_ascii=False)[:300])
                print("  URL:", res["url_after"], "仍有密码框:", res["has_pwd_after"])
                print("  页面提示:", res["msg_text"])
                print("  登录相关请求:", json.dumps(log[-4:], ensure_ascii=False)[:400])
            except Exception as e:
                res["error"] = str(e)[:200]
                print(f"\n===== {kind} {base} ERROR: {e}")
            out[base] = res
            await ctx.close()
        await b.close()
    Path("scripts/login_attempt_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n已写出 scripts/login_attempt_result.json")


asyncio.run(main())

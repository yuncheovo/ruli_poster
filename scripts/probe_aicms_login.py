# -*- coding: utf-8 -*-
"""探明 aicms 登录页的真实提交接口（用无效凭据，仅观察请求地址）。"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


async def main():
    from playwright.async_api import async_playwright
    from ruli_core import launch_chromium

    captured = []
    async with async_playwright() as p:
        b = await launch_chromium(p, headless=True)
        ctx = await b.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
        pg = await ctx.new_page()
        pg.on("request", lambda r: captured.append({
            "m": r.method, "u": r.url, "d": (r.post_data or "")[:300],
            "h": {k: v for k, v in (r.headers or {}).items()
                  if k.lower() in ("authorization", "content-type", "x-requested-with")}
        }) if r.method in ("POST", "PUT") or "/site/" in r.url or "captcha" in r.url.lower() else None)

        await pg.goto("https://aicms-admin.ruli.com/login", wait_until="domcontentloaded", timeout=25000)
        await pg.wait_for_timeout(3000)
        print("登录页 title:", await pg.title())
        info = await pg.evaluate("""() => ({
            inputs: [...document.querySelectorAll('input')].map(i=>({id:i.id,ph:i.placeholder,type:i.type})),
            btns: [...document.querySelectorAll('button, .el-button')].map(b=>(b.innerText||'').trim()).filter(Boolean),
            captchaImg: (document.querySelector('img[src*=captcha]')||{}).src || '',
            text: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,300)
        })""")
        print("输入框:", json.dumps(info["inputs"], ensure_ascii=False))
        print("按钮:", info["btns"], "| 验证码:", info["captchaImg"])
        print("正文:", info["text"])

        # 填假凭据并提交
        try:
            await pg.fill("#admin_username", "13000000000")
            await pg.fill("#admin_pwd", "WrongPass!123")
            await pg.fill("#verify", "0000")
            btns = await pg.query_selector_all("button, .el-button")
            for btn in btns:
                t = (await btn.inner_text() or "").strip()
                if "登录" in t:
                    await btn.click()
                    break
            await pg.wait_for_timeout(4000)
        except Exception as e:
            print("提交异常:", str(e)[:150])

        print("\n--- 捕获请求 ---")
        for c in captured[-15:]:
            print(" ", c["m"], c["u"][:110], "| data:", (c.get("d") or "")[:120], "| hdr:", c.get("h"))
        print("\n提交后 URL:", pg.url)
        txt = await pg.evaluate("()=>(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,300)")
        print("页面提示:", txt)
        Path("scripts/aicms_login_flow.json").write_text(
            json.dumps({"captured": captured, "info": info, "after": txt, "url": pg.url},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        await b.close()

asyncio.run(main())

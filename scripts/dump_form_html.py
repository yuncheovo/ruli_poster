# -*- coding: utf-8 -*-
"""导出 /article/form 完整内联脚本（含上传地址、status 字段、提交后行为）。"""
import asyncio
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
s = requests.Session(); s.headers.update({"User-Agent": UA, "Content-Type": "application/json"})
tok = s.post(f"{api_url}/login/password-login",
             json={"username": cfg["username"], "password": cfg["password"], "remember": True},
             timeout=20).json()["data"]["token"]
H = {"Authorization": f"Bearer {tok}"}
rt = s.post(f"{api_url}/site/app-create-access-token", json={"app": "cengguai"}, headers=H, timeout=20).json()
tv = rt["data"]["token"]["name"]
cms = rt["data"]["url"].replace("/login", "").rstrip("/")


async def main():
    from playwright.async_api import async_playwright
    from ruli_core import launch_chromium
    async with async_playwright() as p:
        b = await launch_chromium(p, headless=True)
        ctx = await b.new_context(user_agent=UA)
        pg = await ctx.new_page()
        await pg.goto(f"{cms}/login?token={tv}", wait_until="domcontentloaded", timeout=25000)
        await pg.wait_for_timeout(2000)
        await pg.goto(f"{cms}/article/form", wait_until="domcontentloaded", timeout=25000)
        await pg.wait_for_timeout(3000)
        html = await pg.content()
        Path("scripts/article_form_full.html").write_text(html, encoding="utf-8")
        js = await pg.evaluate("""() => [...document.querySelectorAll('script:not([src])')]
            .map(s => s.textContent).filter(t => t.trim().length > 40).join('\\n\\n/*====*/\\n\\n')""")
        Path("scripts/article_form_inline.js").write_text(js, encoding="utf-8")
        print("html len:", len(html), "inline js len:", len(js))
        await b.close()

asyncio.run(main())
print("已写出 scripts/article_form_full.html / scripts/article_form_inline.js")

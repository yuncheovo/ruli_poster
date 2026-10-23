# -*- coding: utf-8 -*-
"""抓取独立站 /login 页面完整 HTML + 内联 JS，定位「登录入口错误」的判定逻辑。"""
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

    targets = ["https://admin.cengguai.com",
               "https://hz-admin-yeekang.ruli.com",
               "https://aicms-admin.ruli.com"]
    out = {}
    async with async_playwright() as p:
        b = await launch_chromium(p, headless=True)
        ctx = await b.new_context(user_agent=UA)
        for base in targets:
            pg = await ctx.new_page()
            reqs = []
            pg.on("request", lambda r: reqs.append((r.method, r.url, (r.post_data or "")[:400]))
                  if "/login" in r.url or "captcha" in r.url.lower() else None)
            try:
                await pg.goto(f"{base}/login", wait_until="domcontentloaded", timeout=25000)
                await pg.wait_for_timeout(2500)
            except Exception as e:
                out[base] = {"error": str(e)[:120]}
                await pg.close()
                continue
            dom = await pg.evaluate("""() => {
                const r = {title: document.title, fields: [], forms: [], hasCaptcha: false,
                           bodyText: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,500)};
                document.querySelectorAll('input,select,textarea').forEach(el=>{
                    r.fields.push({name: el.getAttribute('name')||'', type: el.getAttribute('type')||el.tagName.toLowerCase(),
                                   id: el.id||'', placeholder: el.getAttribute('placeholder')||'', cls:(el.className||'').slice(0,60)});
                });
                document.querySelectorAll('form').forEach(f=>r.forms.push({action:f.getAttribute('action')||'', method:(f.getAttribute('method')||'get').toLowerCase(), cls:(f.className||'').slice(0,50)}));
                r.hasCaptcha = !!document.querySelector('img[src*=captcha], [class*=captcha]');
                r.captchaSrc = (document.querySelector('img[src*=captcha]')||{}).src || '';
                return r;
            }""")
            js = await pg.evaluate("""() => [...document.querySelectorAll('script:not([src])')]
                .map(s=>s.textContent).filter(t=>t.trim().length>30).join('\\n\\n/*====*/\\n\\n')""")
            scripts = await pg.evaluate("""() => [...document.querySelectorAll('script[src]')].map(s=>s.getAttribute('src'))""")
            html = await pg.content()
            out[base] = {"dom": dom, "inline_js": js[:6000], "scripts": scripts,
                         "login_requests": reqs,
                         "html_len": len(html)}
            print(f"\n===== {base}")
            print("  title:", dom["title"], "| captcha:", dom["hasCaptcha"], dom["captchaSrc"][:70])
            print("  fields:", json.dumps(dom["fields"], ensure_ascii=False)[:400])
            print("  forms:", json.dumps(dom["forms"], ensure_ascii=False)[:200])
            print("  bodyText:", dom["bodyText"][:200])
            print("  scripts:", scripts[:10])
            print("  login requests:", json.dumps(reqs, ensure_ascii=False)[:400])
            print("  inline js 片段:")
            print("   ", js[:900].replace("\n", " ")[:900])
            await pg.close()
        await b.close()

    Path("scripts/login_pages.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
    print("\n已写出 scripts/login_pages.json")


asyncio.run(main())

# -*- coding: utf-8 -*-
"""用 Playwright 打开真实发文表单页，抓取字段定义与提交请求（不提交，只看）。
流程：控制中心换 token → token URL 进入站点 → 直接导航 /article/form → 解析 DOM。
"""
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

s = requests.Session()
s.headers.update({"User-Agent": UA, "Content-Type": "application/json"})
tok = s.post(f"{api_url}/login/password-login",
             json={"username": cfg["username"], "password": cfg["password"], "remember": True},
             timeout=20).json()["data"]["token"]
H = {"Authorization": f"Bearer {tok}"}

SIG = "cengguai"
rt = s.post(f"{api_url}/site/app-create-access-token", json={"app": SIG}, headers=H, timeout=20).json()
tv = rt["data"]["token"]["name"]
cms = rt["data"]["url"].replace("/login", "").rstrip("/")
print("站点:", cms, "token_len:", len(tv))


async def main():
    from playwright.async_api import async_playwright
    from ruli_core import launch_chromium

    captured = []
    result = {}
    async with async_playwright() as p:
        browser = await launch_chromium(p, headless=True)
        ctx = await browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        def on_request(req):
            if req.method in ("POST", "PUT") and "article" in req.url:
                captured.append({"method": req.method, "url": req.url,
                                 "post_data": (req.post_data or "")[:3000]})
        page.on("request", on_request)

        await page.goto(f"{cms}/login?token={tv}", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2500)
        print("登录后 URL:", page.url)

        await page.goto(f"{cms}/article/form", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(3000)
        result["final_url"] = page.url
        result["title"] = await page.title()

        result["dom"] = await page.evaluate("""() => {
            const out = {fields: [], forms: [], scripts: []};
            document.querySelectorAll('input,textarea,select').forEach(el => {
                const label = el.closest('.layui-form-item, .form-item, .el-form-item');
                out.fields.push({
                    tag: el.tagName.toLowerCase(),
                    name: el.getAttribute('name') || '',
                    id: el.id || '',
                    type: el.getAttribute('type') || el.tagName.toLowerCase(),
                    placeholder: el.getAttribute('placeholder') || '',
                    value: (el.type === 'hidden' ? el.value : ''),
                    label: label ? (label.innerText || '').split('\\n')[0].slice(0, 30) : '',
                    cls: (el.className || '').slice(0, 80)
                });
            });
            document.querySelectorAll('form').forEach(f => out.forms.push({
                action: f.getAttribute('action') || '',
                method: (f.getAttribute('method') || 'get').toLowerCase(),
                id: f.id || '', cls: (f.className||'').slice(0,60)
            }));
            document.querySelectorAll('script').forEach(sc => {
                const src = sc.getAttribute('src');
                if (src) out.scripts.push(src);
            });
            out.hasUeditor = !!document.querySelector('.edui-editor, #ueditor, [id*=ueditor], iframe[id*=ueditor]');
            out.hasTinyMce = !!document.querySelector('.tox-tinymce, .mce-tinymce');
            out.iframes = [...document.querySelectorAll('iframe')].map(f => f.id || f.name || f.src).slice(0,10);
            out.bodyText = (document.body.innerText || '').replace(/\\s+/g,' ').slice(0, 600);
            return out;
        }""")
        print("标题:", result["title"])
        print("字段数:", len(result["dom"]["fields"]))
        for f in result["dom"]["fields"][:30]:
            print("   ", json.dumps(f, ensure_ascii=False))
        print("forms:", json.dumps(result["dom"]["forms"], ensure_ascii=False))
        print("编辑器:", result["dom"]["hasUeditor"], result["dom"]["hasTinyMce"],
              "iframes:", result["dom"]["iframes"])
        print("scripts:", result["dom"]["scripts"][:12])
        print("正文:", result["dom"]["bodyText"][:250])

        # 抓内联脚本里的提交地址
        result["inline_submit"] = await page.evaluate("""() => {
            const hits = [];
            document.querySelectorAll('script:not([src])').forEach(sc => {
                const t = sc.textContent || '';
                ['url:', '/article/', 'ajax', 'submit', 'post('].forEach(kw => {
                    let i = t.indexOf(kw);
                    while (i >= 0 && hits.length < 40) {
                        hits.push(t.slice(Math.max(0,i-120), i+220).replace(/\\s+/g,' '));
                        i = t.indexOf(kw, i+1);
                    }
                });
            });
            return hits.slice(0, 25);
        }""")
        print("\n--- 内联脚本提交线索 ---")
        for h in result["inline_submit"][:12]:
            print("  ", h[:280])

        result["captured"] = captured
        await browser.close()

    Path("scripts/form_dom_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n已写出 scripts/form_dom_result.json")


asyncio.run(main())

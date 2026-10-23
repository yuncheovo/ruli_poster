# -*- coding: utf-8 -*-
"""
Ruli CMS 自动发文工具 - 核心库
支持控制中心登录、一键登录到各CMS站点、文章发布
"""
import json
import time
import re
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from app_paths import app_dir, data_dir


# ============ 常量（默认值，可被实例覆盖） ============
DEFAULT_ADMIN_URL = "https://center-admin.ruli.com"
DEFAULT_API_URL = "https://center-admin-api.ruli.com"


def build_api_url(admin_url: str) -> str:
    """根据控制中心管理地址推导 API 地址。
    规则：center-admin.xxx.com → center-admin-api.xxx.com
    若用户单独配置了 api_url 则直接使用。
    """
    admin_url = (admin_url or "").strip().rstrip("/")
    if not admin_url:
        return DEFAULT_API_URL
    # center-admin.ruli.com → center-admin-api.ruli.com
    if "-admin." in admin_url and "-admin-api." not in admin_url:
        return admin_url.replace("-admin.", "-admin-api.", 1)
    return admin_url


def _js_str(value: str) -> str:
    """安全嵌入 JS 字符串字面量，避免站点名注入/语法错误"""
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


# Playwright 启动参数（无界面后台运行）
_BROWSER_ARGS = ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
# 优先本机 Edge（Win10+ 自带）→ Chrome → 内置/已下载 Chromium
_BROWSER_CHANNELS = ("msedge", "chrome", None)


async def launch_chromium(playwright, *, headless: bool = True):
    """启动浏览器：优先调用用户电脑上的 Edge / Chrome，无需打包 Chromium。"""
    last_err = None
    for channel in _BROWSER_CHANNELS:
        try:
            opts = {"headless": headless, "args": _BROWSER_ARGS}
            if channel:
                opts["channel"] = channel
            browser = await playwright.chromium.launch(**opts)
            if channel:
                print(f"  [浏览器] 使用本机 {channel}")
            return browser
        except Exception as e:
            last_err = e
    raise RuntimeError(
        "未找到可用浏览器。请确认已安装 Microsoft Edge 或 Google Chrome。"
    ) from last_err


def check_browser_available() -> tuple[bool, str]:
    """检测 Playwright 能否启动本机浏览器（供 GUI 提示）。"""
    import asyncio

    async def _probe():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await launch_chromium(p, headless=True)
            await browser.close()

    try:
        asyncio.run(_probe())
        return True, ""
    except Exception as e:
        return False, str(e)

# ============ API客户端 ============

class RuliClient:
    """控制中心API客户端"""
    
    def __init__(self, username: str, password: str, admin_url: str = None, api_url: str = None):
        self.username = username
        self.password = password
        # 控制中心地址（管理端 + API端），可配置
        self.admin_url = (admin_url or DEFAULT_ADMIN_URL).strip().rstrip("/")
        self.api_url = (api_url or build_api_url(self.admin_url)).strip().rstrip("/")
        self.ctrl_token: Optional[str] = None
        self.ctrl_token_expire: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        })
        self.apps: list = []
        self.apps_map: dict = {}
        
    def _auth_header(self) -> dict:
        return {"Authorization": f"Bearer {self.ctrl_token}"}
    
    def login_ctrl(self) -> bool:
        """登录控制中心"""
        try:
            resp = self.session.post(
                f"{self.api_url}/login/password-login",
                json={
                    "username": self.username,
                    "password": self.password,
                    "remember": True
                },
                timeout=15
            )
            data = resp.json()
            if data.get("code") == 0:
                self.ctrl_token = data["data"]["token"]
                self.ctrl_token_expire = data["data"].get("expire_at", "")
                return True
            else:
                print(f"  [!] 登录失败: {data.get('message', '未知错误')}")
                return False
        except Exception as e:
            print(f"  [!] 登录异常: {e}")
            return False
    
    def get_apps(self, page: int = 1, limit: int = 200) -> list:
        """获取应用/站点列表"""
        try:
            resp = self.session.get(
                f"{self.api_url}/site/apps",
                params={"page": page, "limit": limit},
                headers=self._auth_header(),
                timeout=15
            )
            data = resp.json()
            if data.get("code") == 0:
                raw_items = data["data"].get("items", [])
                # 过滤掉控制中心的“内部系统”类应用（如智能内容管理系统），只保留真正的推广站点
                # 实测控制中心返回的分类字段是 categoryText（值如“内部系统”“推广站 / 苟浩然”）
                def _category(app: dict) -> str:
                    return str(
                        app.get("categoryText") or app.get("category") or app.get("classify") or app.get("type") or ""
                    ).strip()
                self.apps = [a for a in raw_items if _category(a) != "内部系统"]
                excluded = len(raw_items) - len(self.apps)
                if excluded:
                    print(f"  [i] 已排除 {excluded} 个内部系统应用")
                # 建立 signature -> app 映射 (用于站点名称查找)
                self.apps_map = {a.get("signature"): a for a in self.apps}
                return self.apps
            return []
        except Exception as e:
            print(f"  [!] 获取app列表失败: {e}")
            return []
    
    def get_app_token(self, signature: str) -> Optional[dict]:
        """获取一键登录token

        返回 data dict 表示成功；返回 None 表示失败（调用方据此判登录失败）。
        失败分两类，打印文案已区分：
          - 站点侧永久性拒绝（"该应用不可用"/"没有权限"/"系统出现错误"等）：站点自身故障，
            非程序可修复，应排除/跳过该站。
          - 网络/超时等：可重试。
        """
        try:
            resp = self.session.post(
                f"{self.api_url}/site/app-create-access-token",
                json={"app": signature},
                headers=self._auth_header(),
                timeout=15
            )
            data = resp.json()
            if data.get("code") == 0:
                return data["data"]
            # 控制中心侧拒绝下发 token（站点域名失效/证书异常/未授权/应用被停用等）。
            # 这类属站点自身故障，非本程序问题，打印原因便于用户直接定位到具体站。
            msg = data.get("message") or data.get("msg") or f"code={data.get('code')}"
            msg = str(msg)
            # 区分“站点不可用/无权限”类永久故障 与 其他
            if any(k in msg for k in ("不可用", "没有权限", "无权限", "系统出现错误", "已停用", "不存在")):
                print(f"  [!] 站点不可用({signature}): {msg[:50]} —— 该站后端拒绝下发登录token，"
                      f"网页控制中心同样无法一键登录，建议从发布列表排除或等站点恢复")
            else:
                print(f"  [!] 控制中心拒绝对 {signature} 下发登录token: {msg[:60]}")
            return None
        except Exception as e:
            print(f"  [!] 获取app token失败 ({signature}): {e}")
            return None
    
    def login_cms_browser(self, signature: str) -> Optional[dict]:
        """通过控制中心一键登录 → 浏览器完成CMS认证
        返回 {api_base, admin_url, cookies} (独立推广站使用session cookie认证)
        或 {token, api_base, admin_url} (aicms类型使用Bearer token)
        """
        cms_url = self.apps_map.get(signature, {}).get("url", "") if hasattr(self, 'apps_map') else ""
        if not cms_url:
            app_data = self.get_app_token(signature)
            if app_data:
                cms_url = app_data["url"]
        
        admin_url = cms_url.replace("/login", "") if cms_url else f"https://admin.{signature}.com"
        
        import asyncio
        async def _login():
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await launch_chromium(p, headless=True)
                ctx = await browser.new_context(
                    viewport={"width":1440,"height":900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                ctrl_page = await ctx.new_page()
                
                # 登录控制中心
                await ctrl_page.goto(f"{self.admin_url}/login", wait_until="domcontentloaded", timeout=15000)
                await ctrl_page.fill('input[placeholder*="手机"]', self.username)
                await ctrl_page.fill('input[type="password"]', self.password)
                await ctrl_page.click('button:has-text("登录")')
                await ctrl_page.wait_for_timeout(3000)
                await ctrl_page.wait_for_load_state("domcontentloaded", timeout=15000)
                
                # 进入子应用
                await ctrl_page.goto(f"{self.admin_url}/go/app", wait_until="domcontentloaded", timeout=15000)
                await ctrl_page.wait_for_timeout(2000)
                await ctrl_page.wait_for_load_state("domcontentloaded", timeout=15000)
                
                # 找到对应站点并点击一键登录
                name = self._get_app_name(signature)
                popup_promise = ctrl_page.wait_for_event("page", timeout=15000)
                
                clicked = await ctrl_page.evaluate(f"""
                    () => {{
                        const name = {_js_str(name)};
                        for (let row of document.querySelectorAll('.el-table__body tr.el-table__row')) {{
                            if (row.textContent.includes(name)) {{
                                row.querySelector('a.el-link--warning')?.click();
                                return true;
                            }}
                        }}
                        return false;
                    }}
                """)
                
                if not clicked:
                    print(f"    [debug] {name} 一键登录未找到可点击行/链接, 改走 token 方式")
                    res = await self._token_nav_login(ctx, signature)
                    await browser.close()
                    return res
                
                try:
                    cms_page = await popup_promise
                    try:
                        await cms_page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    await cms_page.wait_for_timeout(3000)
                    
                    # 提取cookie（用于后续API调用）
                    cookies = await ctx.cookies()
                    admin_host = admin_url.split("://")[1].split("/")[0]
                    session_cookies = {
                        c["name"]: c["value"] for c in cookies
                        if admin_host in c.get("domain", "") or c.get("domain", "") in admin_host
                    }
                    
                    # 对于独立推广站: api_base = admin_url本身 (同一域名)
                    api_base = admin_url
                    
                    result = {
                        "api_base": api_base,
                        "admin_url": admin_url,
                        "cookies": session_cookies,
                        "auth_type": "cookie",
                        "signature": signature,
                        "ctrl_admin_url": self.admin_url,
                    }
                    
                    await cms_page.close()
                    await browser.close()
                    return result
                    
                except Exception as e:
                    print(f"    [debug] {name} 弹窗获取CMS页面失败({e}), 改走 token 方式")
                    res = await self._token_nav_login(ctx, signature)
                    await browser.close()
                    return res
        
        try:
            return asyncio.run(_login())
        except Exception:
            return None
    
    def batch_login_cms(self, signatures: list, concurrency: int = 5,
                         progress_callback=None) -> dict:
        """批量并发一键登录多个CMS站点
        
        利用 Playwright 多 browser context 同时登录，大幅缩短登录时间。
        36个站点: 串行登录≈9分钟 → 并发登录≈2分钟(并发度5)
        
        Args:
            signatures: 站点 signature 列表
            concurrency: 并发度(默认5)
            progress_callback: 可选, 每完成一个站点时回调 callback(sig, ok)
        
        Returns:
            {signature: cms_info_dict, ...}  失败的站点值为 None
        """
        if not self.apps:
            self.get_apps()
        
        name_map = {}
        url_map = {}
        for app in self.apps:
            sig = app.get("signature", "")
            name_map[sig] = app.get("name", sig)
            url_map[sig] = app.get("url", "")
        
        import asyncio
        from playwright.async_api import async_playwright
        
        UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

        async def _login_ctrl(ctx):
            """在给定 context 中完成一次控制中心登录（仅用于首批/补登录）"""
            import os, time as _t
            page = None
            try:
                page = await ctx.new_page()
                await page.goto(f"{self.admin_url}/login", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(500)
                await page.fill('input[placeholder*="手机"]', self.username)
                await page.fill('input[type="password"]', self.password)
                await page.click('button:has-text("登录")')
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(3000)
                # 成败判定改为“看页面内容”而非“看 URL”:
                # 该 SPA 登录成功后地址栏仍可能保留 /login, 用 URL 判断会得到假阴性。
                # 成功 => 登录表单(密码框)已消失, 或页面出现控制台特征(系统概况/恭喜登录成功)。
                info = await page.evaluate("""() => {
                    const hasPwd = !!document.querySelector('input[type="password"]');
                    const txt = (document.body && document.body.innerText) || '';
                    const hasDash = txt.includes('系统概况') || txt.includes('恭喜您，登录成功')
                                   || txt.includes('子应用') || txt.includes('账号数');
                    return {hasPwd: hasPwd, hasDash: hasDash};
                }""")
                ok = (not info["hasPwd"]) or info["hasDash"]
                if not ok:
                    try:
                        os.makedirs("logs", exist_ok=True)
                        shot = f"logs/login_fail_{int(_t.time())}.png"
                        await page.screenshot(path=shot, full_page=True)
                        txt = await page.evaluate("() => (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,300)")
                        print(f"  [!] 控制中心登录失败(仍停留登录页) 截图={shot}")
                        print(f"  [!] 页面提示: {txt.strip()[:200]}")
                    except Exception:
                        pass
                return ok
            except Exception as e:
                print(f"  [!] 控制中心登录异常: {e}")
                try:
                    os.makedirs("logs", exist_ok=True)
                    await page.screenshot(path=f"logs/login_fail_exc_{int(_t.time())}.png", full_page=True)
                except Exception:
                    pass
                return False
            finally:
                if page is not None:
                    try:
                        await page.close()
                    except Exception:
                        pass

        async def _one_click(ctx, sig, app_name):
            """ctx 已含控制中心认证 cookie → 一键登录取回站点 cookie（不再重复登录）"""
            # aicms 子站(ruli.com): 一键登录不弹窗, 直接用 API Bearer 方式(无需浏览器/不触发限频)
            if "ruli.com" in url_map.get(sig, ""):
                try:
                    return self.login_cms(sig)
                except Exception:
                    return None
            page = None
            cms_page = None
            try:
                page = await ctx.new_page()
                await page.goto(f"{self.admin_url}/go/app", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1500)
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                # 会话失效被踢回登录页时，仅补一次登录（不会成片触发限频）
                if "/login" in page.url:
                    if not await _login_ctrl(ctx):
                        return None
                    await page.goto(f"{self.admin_url}/go/app", wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(1500)
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)

                app_url = url_map.get(sig, "")
                # aicms 子站: 一键登录不弹窗, 直接走 token URL。
                # 但合作站 hz-admin-*.ruli.com 虽含 ruli.com，实为独立 CMS 部署，
                # 与独立推广站一样靠一键登录弹窗认证，不能按 aicms 跳过弹窗。
                is_cooperation = "hz-admin-" in app_url
                is_aicms = "ruli.com" in app_url and not is_cooperation

                cms_page = None
                fail_reason = ""
                if is_cooperation:
                    # 合作站(hz-admin-*.ruli.com): 实测“登录”按钮在自动化下不会弹出新窗口，
                    # 但 app-create-access-token + {url}?token= 直导在共享 ctx 内已验证可拿到 SESSID。
                    # 跳过必然超时的弹窗等待，直接走 token 通道，省去 15s 空等。
                    return await self._token_nav_login(ctx, sig)
                if not is_aicms:
                    # 独立推广站: 先等弹窗(一键登录弹出新页面)
                    # 等表格渲染完成再点, 避免并发下表格未就绪导致点击落空
                    try:
                        await page.wait_for_selector(
                            '.el-table__body tr.el-table__row', timeout=10000)
                    except Exception:
                        fail_reason = "app列表表格未渲染"
                    clicked = False
                    if not fail_reason:
                        clicked = await page.evaluate(f"""
                            () => {{
                                const name = {_js_str(app_name)};
                                for (let row of document.querySelectorAll('.el-table__body tr.el-table__row')) {{
                                    if (row.textContent.includes(name)) {{
                                        const link = row.querySelector('a.el-link--warning')
                                            || [...row.querySelectorAll('a,button')].find(e => /登录|一键/.test(e.textContent));
                                        (link || row.querySelector('a') || row)?.click();
                                        return true;
                                    }}
                                }}
                                return false;
                            }}
                        """)
                    if clicked:
                        popup_promise = page.wait_for_event("page", timeout=15000)
                        try:
                            cms_page = await popup_promise
                        except Exception:
                            cms_page = None
                        # 未捕获到新标签页弹窗时, 若当前页已离开 /go/app 跳到了 CMS, 复用当前页
                        if cms_page is None and "/go/app" not in page.url and "/login" not in page.url:
                            cms_page = page
                            fail_reason = ""
                        if cms_page is None:
                            fail_reason = fail_reason or "一键登录弹窗超时"
                    else:
                        fail_reason = fail_reason or "未在表格中找到该行(名称不匹配)"

                if cms_page is None:
                    # 独立站不弹窗(如 yypcs) → token URL cookie 导航(共享 ctx, 不重新登录控制中心)
                    if fail_reason:
                        print(f"    [debug] {app_name} 一键登录未走弹窗: {fail_reason} → 尝试 token 方式")
                    return await self._token_nav_login(ctx, sig)

                try:
                    await cms_page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                await cms_page.wait_for_timeout(2000)

                # 提取站点 cookie
                cookies = await ctx.cookies()
                admin_domain = cms_page.url.split("://")[1].split("/")[0]
                session_cookies = {}
                for c in cookies:
                    domain = c.get('domain', '')
                    if admin_domain in domain or domain in admin_domain:
                        session_cookies[c['name']] = c['value']

                api_base = cms_page.url.split("/article")[0] if "/article" in cms_page.url else \
                           cms_page.url.rsplit("?", 1)[0].rstrip("/")
                if api_base.endswith("/login"):
                    api_base = api_base.rsplit("/", 1)[0]

                return {
                    "api_base": api_base,
                    "admin_url": api_base,
                    "cookies": session_cookies if session_cookies else {},
                    "auth_type": "cookie",
                    "signature": sig,
                    "ctrl_admin_url": self.admin_url,
                }
            except Exception:
                return None
            finally:
                # 若 cms_page 复用了当前 page(同标签页跳转), 只关一次
                try:
                    if cms_page is not None and cms_page is not page:
                        await cms_page.close()
                except Exception:
                    pass
                try:
                    if page is not None:
                        await page.close()
                except Exception:
                    pass

        async def _batch_login(sigs, pcb=None):
            """整个批次只用同一个 context 登录一次控制中心, 各站点在该 context
            内并发开新页面做一键登录。

            登录态(无论 cookie 还是 localStorage)都留在这个共享 context 中,
            既不会因为并发重复登录控制中心而触发限频, 也不会因只复制 cookie
            而丢失 localStorage 里的登录态(之前 cookie 复用方案整批秒失败的根因)。
            """
            results = {}
            async with async_playwright() as p:
                browser = await launch_chromium(p, headless=True)

                ctx = await browser.new_context(
                    viewport={"width":1440, "height":900},
                    user_agent=UA
                )
                if not await _login_ctrl(ctx):
                    await ctx.close()
                    await browser.close()
                    if pcb:
                        for s in sigs:
                            pcb(s, False)
                    return {s: None for s in sigs}

                sem = asyncio.Semaphore(max(1, concurrency))

                async def _work(sig):
                    async with sem:
                        try:
                            return await asyncio.wait_for(
                                _one_click(ctx, sig, name_map.get(sig, sig)),
                                timeout=45
                            )
                        except Exception:
                            return None

                gathered = await asyncio.gather(
                    *[_work(s) for s in sigs], return_exceptions=True
                )
                for sig, r in zip(sigs, gathered):
                    ok = (not isinstance(r, Exception)) and r is not None
                    results[sig] = r if ok else None
                    if pcb:
                        pcb(sig, ok)

                await ctx.close()
                await browser.close()
            return results
        
        try:
            import traceback
            return asyncio.run(_batch_login(signatures, progress_callback))
        except Exception as e:
            traceback.print_exc()
            print(f"  [!] 批量登录异常: {e}")
            # 即使异常也返回结果(全部None，不阻塞发布)
            return {sig: None for sig in signatures}
    
    def _get_app_name(self, signature: str) -> str:
        """根据signature获取应用名称"""
        if hasattr(self, 'apps') and self.apps:
            for app in self.apps:
                if app.get("signature") == signature:
                    return app.get("name", signature)
        return signature
    
    def _login_cms_via_token(self, signature: str) -> Optional[dict]:
        """通过API token + Playwright直接访问CMS (适用于一键登录不弹窗的站点)"""
        app_data = self.get_app_token(signature)
        if not app_data:
            return None
        token = app_data["token"]["name"]
        cms_url = app_data["url"]
        admin_url = cms_url.replace("/login", "")
        
        import asyncio
        async def _do():
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await launch_chromium(p, headless=True)
                ctx = await browser.new_context(
                    viewport={"width":1440,"height":900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = await ctx.new_page()
                
                login_url = f"{cms_url}?token={token}"
                try:
                    await page.goto(login_url, wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    await browser.close()
                    return None
                await page.wait_for_timeout(5000)

                current = page.url
                cookies = await ctx.cookies()
                admin_domain = current.split("://")[1].split("/")[0]
                sc = {}
                for c in cookies:
                    domain = c.get("domain", "")
                    if admin_domain in domain or domain in admin_domain:
                        sc[c["name"]] = c["value"]

                # 不以地址栏含 /login 直接判失败, 以是否拿到站点 cookie 为准
                if not sc:
                    await browser.close()
                    return None

                await browser.close()
                
                if not sc:
                    return None
                return {
                    "api_base": admin_url, "admin_url": admin_url,
                    "cookies": sc, "auth_type": "cookie", "signature": signature,
                    "ctrl_admin_url": self.admin_url,
                }
        
        try:
            return asyncio.run(_do())
        except Exception:
            return None

    async def _token_nav_login(self, ctx, signature: str) -> Optional[dict]:
        """在给定(已登录控制中心的) context 内用 token URL 直接导航 CMS, 取回 cookie。
        与 _login_cms_via_token 等价, 但是 async 版本, 可在批量事件循环内调用(不另起 asyncio.run)。
        """
        try:
            ad = self.get_app_token(signature)
            if not ad:
                return None
            tok = ad.get("token")
            token = tok.get("name") if isinstance(tok, dict) else tok
            cms_url = ad.get("url", "")
            if not token or not cms_url:
                return None
            nav = await ctx.new_page()
            try:
                await nav.goto(f"{cms_url}?token={token}",
                               wait_until="domcontentloaded", timeout=15000)
                await nav.wait_for_timeout(4000)
                cookies = await ctx.cookies()
                admin_domain = nav.url.split("://")[1].split("/")[0]
                sc = {}
                for c in cookies:
                    d = c.get("domain", "")
                    if admin_domain in d or d in admin_domain:
                        sc[c["name"]] = c["value"]
                # 不再单纯以地址栏是否含 /login 判成败(部分站 token 登录后地址栏仍残留 /login
                # 片段但已下发 cookie); 以是否实际拿到站点 cookie 为准。
                if not sc:
                    print(f"    [debug] {signature} token方式未拿到站点cookie (url={nav.url[:80]})")
                    return None
                admin_url = cms_url.replace("/login", "")
                return {
                    "api_base": admin_url, "admin_url": admin_url,
                    "cookies": sc, "auth_type": "cookie", "signature": signature,
                    "ctrl_admin_url": self.admin_url,
                }
            finally:
                await nav.close()
        except Exception:
            return None

    def login_cms(self, signature: str, use_browser: bool = False) -> Optional[dict]:
        """登录目标CMS
        对于独立推广站(admin.xxx.com): 使用浏览器一键登录(获得session cookie)
        对于aicms子站: 尝试API token方式, 失败则用浏览器
        
        返回 {api_base, admin_url, cookies, auth_type} 或 {token, api_base, admin_url}
        """
        if use_browser:
            return self.login_cms_browser(signature)
        
        app_data = self.get_app_token(signature)
        if not app_data:
            # 没有app token，尝试浏览器方式
            return self.login_cms_browser(signature)
        
        token = app_data["token"]["name"]
        cms_url = app_data["url"]
        admin_url = cms_url.replace("/login", "")
        domain = cms_url.split("://")[1].split("/")[0]
        
        # 判断站点类型
        # 合作站 hz-admin-*.ruli.com 虽含 ruli.com，实为独立 CMS 部署：
        # 有 /login 页面、用 SESSID cookie 认证，与独立推广站同处理。
        # 若按 "ruli.com" 归入 aicms，会走 take-new-token 接口而该接口对其返回 404，
        # 导致登录必然失败。
        is_cooperation = domain.startswith("hz-admin-")
        is_independent = (domain.startswith("admin.") and "ruli.com" not in domain) or is_cooperation
        is_aicms = "ruli.com" in domain and not is_cooperation
        
        if is_independent:
            # 独立推广站: 优先浏览器一键登录(弹窗), 失败则API token直接访问
            result = self.login_cms_browser(signature)
            if result:
                return result
            # 一键登录弹窗失败(如yypcs) → fallback到token URL方式
            return self._login_cms_via_token(signature)
        
        if is_aicms:
            # aicms: 尝试API方式
            api_candidates = []
            if "-admin." in domain:
                api_candidates.append(domain.replace("-admin.", "-admin-api."))
            if domain.startswith("admin."):
                api_candidates.append(domain.replace("admin.", "admin-api.", 1))
            api_candidates.append(domain)
            
            for api_domain in api_candidates:
                cms_api_base = f"{cms_url.split('://')[0]}://{api_domain}"
                try:
                    s = requests.Session()
                    s.headers.update({
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/plain, */*",
                    })
                    s.get(cms_url, timeout=10)
                    
                    token_resp = s.post(
                        f"{cms_api_base}/site/take-new-token",
                        json={"token": token},
                        timeout=10
                    )
                    if token_resp.status_code != 200:
                        continue
                    data = token_resp.json()
                    if data.get("code") == 0:
                        return {
                            "token": data["data"]["token"],
                            "api_base": cms_api_base,
                            "admin_url": admin_url,
                            "auth_type": "bearer",
                            "signature": signature,
                            "ctrl_admin_url": self.admin_url,
                        }
                except Exception:
                    continue
        
        # 兜底: aicms 浏览器方式无效(不弹窗), 直接返回 None, 不浪费控制中心登录
        return None
    
    def fetch_cms_categories(self, signature: str, force_refresh: bool = False) -> list:
        """获取CMS栏目列表（浏览器辅助，自动缓存），返回 [(id, name), ...]"""
        # 先尝试缓存
        if not force_refresh:
            cached = CMSPoster.get_categories_cached(signature)
            if cached is not None:
                flat = []
                for c in cached:
                    cid = c.get("id", c.get("category_id", ""))
                    cname = c.get("name", c.get("title", ""))
                    if cid:
                        flat.append((str(cid), str(cname)))
                    for child in c.get("children", c.get("child", [])):
                        cid2 = child.get("id", child.get("category_id", ""))
                        if cid2:
                            flat.append((str(cid2), f"  {child.get('name','')}"))
                return flat
        
        cms_info = self.login_cms(signature)
        if not cms_info:
            return []
        poster = CMSPoster(cms_info)
        return poster.get_categories_flat(force_refresh=force_refresh)


class CMSPoster:
    """CMS文章发布器 - 支持独立推广站(cookie auth)和aicms(bearer token)两种模式"""
    
    # 已知的文章发布API端点(按优先级)
    PUBLISH_ENDPOINTS = [
        "/article/form",            # ✅ 已确认: 独立推广站 (POST, JSON)
        "/content/article/add",     # aicms备用
        "/api/article/add",
        "/api/article/create",
        "/api/content/create",
    ]
    
    # 分类/栏目API端点
    CATEGORY_ENDPOINTS = [
        "/article/category-tree",      # ✅ 已确认: 独立推广站
        "/common/article-categorys",   # ✅ 已确认: 备用
        "/common/sites",               # aicms: 站点列表(可作为栏目)
        "/common/modules",             # aicms: 模块列表
        "/content/category/list",
        "/api/category/list",
    ]
    
    # 图片上传端点
    UPLOAD_ENDPOINTS = [
        "/site/upload",
        "/site/ueditor-plus",  # UEditor-Plus
        "/api/upload",
    ]
    
    # 栏目缓存文件路径（用户数据目录，升级/换目录不丢）
    CATEGORY_CACHE_FILE = str(data_dir() / "category_cache.json")
    
    def __init__(self, cms_info: dict):
        self.api_base = cms_info.get("api_base", "")
        self.admin_url = cms_info.get("admin_url", "")
        # 控制中心管理地址（用于浏览器方式上传封面图），可配置
        self.ctrl_admin_url = cms_info.get("ctrl_admin_url", DEFAULT_ADMIN_URL)
        self.auth_type = cms_info.get("auth_type", "bearer")
        self.app_data = cms_info.get("app_data", {})
        self.signature = cms_info.get("signature", "")
        self.last_error = ""
        # 失败类型：ok / business(接口明确拒绝) / network(被拦截·限流·超时,属瞬时) / no_endpoint(全404)
        self.last_error_kind = "ok"
        
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        })
        
        if self.auth_type == "bearer":
            self.session.headers["Authorization"] = f"Bearer {cms_info.get('token', '')}"
        elif self.auth_type == "cookie":
            host = ""
            try:
                host = self.api_base.split("://", 1)[1].split("/")[0]
            except (IndexError, AttributeError):
                host = ""
            for k, v in cms_info.get("cookies", {}).items():
                if host:
                    self.session.cookies.set(k, v, domain=host)
                else:
                    self.session.cookies.set(k, v)
        
        self.categories: list = []
        self.sites: list = []
    
    @classmethod
    def _load_cache(cls) -> dict:
        """加载栏目缓存文件"""
        if not os.path.exists(cls.CATEGORY_CACHE_FILE):
            return {}
        try:
            with open(cls.CATEGORY_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    
    @classmethod
    def _save_cache(cls, cache: dict):
        """保存栏目缓存文件"""
        try:
            with open(cls.CATEGORY_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    
    @classmethod
    def get_categories_cached(cls, signature: str) -> Optional[list]:
        """从缓存读取栏目列表，不需要登录。返回 [(id, name), ...] 或 None（缓存未命中）"""
        cache = cls._load_cache()
        entry = cache.get(signature)
        if entry:
            cats = entry.get("categories", [])
            if cats:
                return cats
        return None
    
    @classmethod
    def clear_cache(cls, signature: str = None):
        """清除缓存
        Args:
            signature: 指定站点清除，None则清除全部
        """
        if signature:
            cache = cls._load_cache()
            cache.pop(signature, None)
            cls._save_cache(cache)
        else:
            if os.path.exists(cls.CATEGORY_CACHE_FILE):
                os.remove(cls.CATEGORY_CACHE_FILE)
    
    def _api_url(self, path: str) -> str:
        """构建API URL"""
        if path.startswith("http"):
            return path
        return f"{self.api_base}{path}"
    
    def get_categories(self, force_refresh: bool = False) -> list:
        """获取栏目/分类列表（优先从缓存读取）"""
        if not force_refresh:
            cached = self.get_categories_cached(self.signature)
            if cached is not None:
                self.categories = cached
                return self.categories
        
        # 从API获取
        for ep in self.CATEGORY_ENDPOINTS:
            try:
                url = self._api_url(ep)
                resp = self.session.get(url, timeout=10)
                data = resp.json()
                if data.get("code") == 0 and "data" in data:
                    raw = data["data"]
                    if isinstance(raw, list):
                        self.categories = raw
                    elif isinstance(raw, dict) and "items" in raw:
                        self.categories = raw["items"]
                    elif isinstance(raw, dict) and "list" in raw:
                        self.categories = raw["list"]
                    if self.categories:
                        break  # 拿到了数据就停
                    else:
                        continue  # 空列表不算有效响应，试下一个
                # 端点返回了但code!=0或结构不匹配
                continue
            except Exception:
                continue
        
        # 仅缓存非空结果，避免永久缓存失败态
        if self.signature and self.categories:
            cache = self._load_cache()
            cache[self.signature] = {
                "categories": self.categories,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "api_base": self.api_base
            }
            self._save_cache(cache)
        
        return self.categories if self.categories else []
    
    def refresh_categories(self) -> list:
        """强制从API刷新栏目列表（同时更新缓存）"""
        return self.get_categories(force_refresh=True)
    
    def get_categories_flat(self, force_refresh: bool = False) -> list:
        """获取栏目列表（简化版：返回 [(id, name), ...]）
        
        Args:
            force_refresh: True=强制从API重新获取
        """
        cats = self.get_categories(force_refresh=force_refresh)
        result = []
        for c in cats:
            cid = c.get("id", c.get("category_id", c.get("catid", "")))
            cname = c.get("name", c.get("title", c.get("category_name", "")))
            if cid:
                result.append((str(cid), str(cname)))
            children = c.get("children", c.get("child", []))
            for child in (children or []):
                cid2 = child.get("id", child.get("category_id", ""))
                cname2 = child.get("name", child.get("title", ""))
                if cid2:
                    result.append((str(cid2), f"  {cname2}"))
        return result
    
    def get_sites(self) -> list:
        """获取CMS内的多站点列表"""
        endpoints = ["/site/list", "/api/site/list", "/content/site/list"]
        for ep in endpoints:
            try:
                resp = self.session.get(self._api_url(ep), timeout=10)
                data = resp.json()
                if data.get("code") == 0 and "data" in data:
                    self.sites = data["data"] if isinstance(data["data"], list) else data["data"].get("items", [])
                    return self.sites
            except Exception:
                continue
        return []
    
    def upload_image(self, file_path: str) -> Optional[str]:
        """上传图片，返回URL"""
        try:
            # Session 默认 Content-Type: application/json 会破坏 multipart 上传
            headers = {
                k: v for k, v in self.session.headers.items()
                if k.lower() != "content-type"
            }
            with open(file_path, "rb") as f:
                resp = self.session.post(
                    self._api_url(self.UPLOAD_ENDPOINTS[0]),
                    files={"file": (os.path.basename(file_path), f)},
                    headers=headers,
                    timeout=30
                )
            data = resp.json()
            if data.get("code") == 0:
                return data["data"].get("url", data["data"].get("path", ""))
        except Exception as e:
            print(f"  [!] 上传图片失败: {e}")
        return None
    
    def publish_article(self, article: dict) -> bool:
        """发布文章 - 使用已确认的API端点
        
        Article dict 应包含:
          - title (必填): 文章标题
          - content (必填): 文章内容(HTML)
          - category_id: 分类ID
          - keywords: SEO关键词
          - description: SEO描述
          - published_at / publish_time: 发布日期 (YYYY-MM-DD HH:MM:SS)
          - image: 封面图URL
          - view_count: 浏览量(默认0)
        """
        # 构建标准文章发布载荷
        # status: 0=待发布, 1=已发布
        cat_id = article.get("category_id", article.get("category", "1"))
        published_at = (
            article.get("published_at")
            or article.get("publish_time")
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        payload = {
            "id": article.get("id", ""),
            "title": article.get("title", ""),
            "category_id": int(cat_id) if str(cat_id).isdigit() else cat_id,
            "image": article.get("image", article.get("cover", "")),
            "file": article.get("file", ""),
            "keywords": article.get("keywords", ""),
            "description": article.get("description", ""),
            "view_count": str(article.get("view_count", 0)),
            "published_at": published_at,
            "content": article.get("content", ""),
            "status": article.get("status", 1),  # 默认已发布 (1=已发布, 0=待发布)
        }
        
        # 失败类型：先假定所有端点都 404（接口路径不存在）
        self.last_error_kind = "no_endpoint"
        biz_msg = ""
        net_hint = ""

        for ep in self.PUBLISH_ENDPOINTS:
            # 1) 网络层异常（超时/连接失败）：瞬时故障，换端点继续探测
            try:
                resp = self.session.post(
                    self._api_url(ep),
                    json=payload,
                    timeout=30
                )
            except Exception as e:
                net_hint = f"{ep} 网络异常({type(e).__name__})"
                self.last_error_kind = "network"
                continue

            # 2) 404 = 该端点不存在，继续探测下一个
            if resp.status_code == 404:
                continue

            # 3) 非 2xx：多为 WAF/限流/鉴权过期（403/429/5xx），属瞬时故障。
            #    注意：绝不能把它当成"站点坏了"，否则会把整批站点永久标记掉。
            if resp.status_code >= 400:
                snippet = (resp.text or "").replace("\n", " ")[:120]
                net_hint = f"{ep} HTTP{resp.status_code} {snippet}"
                self.last_error_kind = "network"
                continue

            # 4) 2xx 但响应不是 JSON（被网关返回 HTML 拦截页等）
            try:
                data = resp.json()
            except Exception:
                snippet = (resp.text or "").replace("\n", " ")[:120]
                net_hint = f"{ep} 非JSON响应 {snippet}"
                self.last_error_kind = "network"
                continue

            if data.get("code") == 0:
                print(f"    [OK] 发布成功 via {ep} → {data.get('message', '')}")
                return True

            # 5) 接口存在且明确拒绝（业务失败），停止探测避免误判
            msg = (data.get("message") or "").strip()
            if msg and "not found" not in msg.lower():
                print(f"    [!] {ep} 返回错误: {msg}")
                self.last_error = f"{ep}: {msg}"
                self.last_error_kind = "business"
                return False
            biz_msg = msg or "接口返回 code!=0"
            self.last_error_kind = "business"

        # 全部端点都试过了仍未成功 —— 按类型给出真实原因
        if self.last_error_kind == "network":
            self.last_error = f"网络/被拦截: {net_hint}"
        elif self.last_error_kind == "business":
            self.last_error = f"业务拒绝: {biz_msg}"
        else:
            self.last_error = "未找到可用的发布接口(所有端点均404)"
        print(f"    [!] 发布失败：{self.last_error}")
        return False
    
    def schedule_article(self, article: dict, publish_time: str) -> bool:
        """定时发布文章"""
        article["published_at"] = publish_time
        return self.publish_article(article)
    
    def upload_cover_via_browser(self, image_path: str, username: str, password: str,
                                  signature: str, ctrl_admin_url: str = None) -> Optional[str]:
        """通过浏览器上传封面图并返回URL
        
        Playwright打开CMS文章表单 → 上传封面图 → 捕获图片URL
        适用于独立推广站 (需要浏览器cookie认证)
        
        Args:
            image_path: 本地图片文件路径
            username/password: 控制中心登录凭据
            signature: 站点signature
            ctrl_admin_url: 控制中心管理地址 (默认 center-admin.ruli.com)
        
        Returns:
            上传后的图片URL, 失败返回None
        """
        if not os.path.exists(image_path):
            print(f"  [!] 封面图不存在: {image_path}")
            return None
        
        ctrl_admin = (ctrl_admin_url or DEFAULT_ADMIN_URL).strip().rstrip("/")
        
        import asyncio
        result_url = None
        
        async def _upload():
            nonlocal result_url
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await launch_chromium(p, headless=True)
                ctx = await browser.new_context(
                    viewport={"width":1440,"height":900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                ctrl_page = await ctx.new_page()
                
                # 1. 登录控制中心
                await ctrl_page.goto(f"{ctrl_admin}/login", wait_until="networkidle")
                await ctrl_page.fill('input[placeholder*="手机"]', username)
                await ctrl_page.fill('input[type="password"]', password)
                await ctrl_page.click('button:has-text("登录")')
                await ctrl_page.wait_for_timeout(3000)
                await ctrl_page.wait_for_load_state("networkidle")
                
                # 2. 进入子应用
                await ctrl_page.goto(f"{ctrl_admin}/go/app")
                await ctrl_page.wait_for_timeout(2000)
                await ctrl_page.wait_for_load_state("networkidle")
                
                # 3. 找到app名称
                app_name = await ctrl_page.evaluate(f"""
                    async () => {{
                        const r = await fetch({_js_str(build_api_url(ctrl_admin) + '/site/apps?page=1&limit=200')}, {{
                            headers: {{ Authorization: localStorage.getItem('control:token') }}
                        }});
                        const data = await r.json();
                        const target = {_js_str(signature)};
                        for (let app of data.data.items) {{
                            if (app.signature === target) return app.name;
                        }}
                        return target;
                    }}
                """)
                
                # 4. 点击一键登录
                popup_promise = ctx.wait_for_event("page", timeout=30000)
                await ctrl_page.evaluate(f"""
                    () => {{
                        const name = {_js_str(app_name)};
                        for (let row of document.querySelectorAll('.el-table__body tr.el-table__row')) {{
                            if (row.textContent.includes(name)) {{
                                row.querySelector('a.el-link--warning')?.click();
                                break;
                            }}
                        }}
                    }}
                """)
                
                cms_page = await popup_promise
                try:
                    await cms_page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await cms_page.wait_for_timeout(4000)
                
                # 5. 监听网络请求，捕获上传响应
                upload_responses = []
                
                async def on_resp(response):
                    if response.status == 200 and '/site/' in response.url and 'upload' in response.url.lower():
                        try:
                            body = await response.text()
                            data = json.loads(body)
                            if data.get("code") == 0:
                                url = data.get("data", {}).get("url", "")
                                if url:
                                    upload_responses.append(url)
                        except Exception:
                            pass
                    # 也捕获UEditor上传响应
                    if response.status == 200 and 'ueditor' in response.url.lower():
                        try:
                            body = await response.text()
                            data = json.loads(body)
                            if data.get("state") == "SUCCESS":
                                url = data.get("url", "")
                                if url:
                                    upload_responses.append(url)
                        except Exception:
                            pass
                
                cms_page.on("response", on_resp)
                
                # 6. 访问文章表单
                form_url = f"{self.admin_url}/article/form"
                await cms_page.goto(form_url, wait_until="networkidle", timeout=15000)
                await cms_page.wait_for_timeout(2000)
                
                # 7. 上传封面图（通过file input）
                abs_path = os.path.abspath(image_path).replace("\\", "/")
                
                try:
                    file_input = await cms_page.query_selector('input[name="file"]')
                    if file_input:
                        await file_input.set_input_files(abs_path)
                        await cms_page.wait_for_timeout(3000)
                        
                        # 等待上传完成（检查image hidden字段是否被填充）
                        await cms_page.wait_for_function("""
                            () => {
                                const imgInput = document.querySelector('input[name="image"]');
                                return imgInput && imgInput.value && imgInput.value.length > 0;
                            }
                        """, timeout=10000)
                        
                        # 读取image字段的值
                        result_url = await cms_page.evaluate("""
                            () => document.querySelector('input[name="image"]')?.value || ''
                        """)
                    else:
                        print(f"    [!] 未找到封面图上传按钮")
                except Exception as e:
                    print(f"    [!] 上传异常: {e}")
                
                await cms_page.close()
                await browser.close()
        
        try:
            asyncio.run(_upload())
        except Exception as e:
            print(f"    [!] 浏览器上传封面图失败: {e}")
            return None
        
        return result_url if result_url else None
    
    def upload_and_publish(self, article: dict, cover_path: str = None,
                           username: str = "", password: str = "",
                           signature: str = "", ctrl_admin_url: str = None) -> bool:
        """上传封面图并发布文章（一站式）
        
        如果有cover_path，先上传封面图，再发布
        """
        if cover_path and os.path.exists(cover_path):
            print(f"    上传封面图...")
            image_url = self.upload_cover_via_browser(
                cover_path, username, password, signature,
                ctrl_admin_url=ctrl_admin_url or self.ctrl_admin_url
            )
            if image_url:
                print(f"    封面URL: {image_url}")
                article["image"] = image_url
            else:
                print(f"    [!] 封面图上传失败，继续发布（无封面）")
        
        return self.publish_article(article)


# ============ 文章解析器 ============

class ArticleParser:
    """从文件解析文章 - 标题固定为文件名，不解析tags/category"""
    
    @staticmethod
    def parse_markdown(file_path: str) -> dict:
        """解析Markdown文件，标题=文件名"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        
        filename = Path(file_path).stem
        
        # 如果有YAML front matter，剥离它（但不解析）
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()
        
        return {
            "title": filename,
            "content": content,
            "source_file": file_path,
        }
    
    @staticmethod
    def parse_html(file_path: str) -> dict:
        """解析HTML文件，标题=文件名"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        
        filename = Path(file_path).stem
        
        # 提取body内容
        body_match = re.search(r"<body[^>]*>(.+?)</body>", content, re.DOTALL | re.IGNORECASE)
        body = body_match.group(1) if body_match else content
        
        return {
            "title": filename,
            "content": body,
            "source_file": file_path,
        }
    
    @staticmethod
    def parse_txt(file_path: str) -> dict:
        """解析纯文本文件，标题=文件名，内容=全部文件内容"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        
        return {
            "title": Path(file_path).stem,
            "content": content,
            "source_file": file_path,
        }
    
    @classmethod
    def parse_file(cls, file_path: str) -> dict:
        """自动识别文件类型并解析"""
        ext = Path(file_path).suffix.lower()
        if ext in (".md", ".markdown"):
            return cls.parse_markdown(file_path)
        elif ext in (".html", ".htm"):
            return cls.parse_html(file_path)
        else:
            return cls.parse_txt(file_path)
    
    _COUNT_CACHE: dict = {}  # path -> (mtime_key, count)
    _ARTICLE_EXTS = {".txt", ".md", ".markdown", ".html", ".htm"}

    @classmethod
    def count_folder(cls, folder_path: str, recursive: bool = True,
                     max_depth: int = 6, max_files: int = 0) -> int:
        """仅统计文章文件数量（带缓存，适合 UI 刷新）
        
        Args:
            max_files: 0 表示不限制（默认），>0 时到达该数量即停止扫描（防御性上限）
        """
        if not folder_path:
            return 0
        folder = Path(folder_path)
        if not folder.exists():
            return 0
        try:
            mtime_key = (str(folder.resolve()), folder.stat().st_mtime_ns)
        except OSError:
            mtime_key = (str(folder), 0)
        cached = cls._COUNT_CACHE.get(mtime_key[0])
        if cached and cached[0] == mtime_key[1]:
            return cached[1]

        count = 0
        import os as _os

        def scan(current_path, depth):
            nonlocal count
            if (max_files and count >= max_files) or depth > max_depth:
                return
            try:
                with _os.scandir(current_path) as entries:
                    for entry in entries:
                        if max_files and count >= max_files:
                            return
                        if entry.is_dir(follow_symlinks=False):
                            if recursive and depth < max_depth:
                                scan(entry.path, depth + 1)
                        elif entry.is_file(follow_symlinks=False):
                            ext = _os.path.splitext(entry.name)[1].lower()
                            if ext in cls._ARTICLE_EXTS:
                                count += 1
            except (PermissionError, OSError):
                pass

        scan(str(folder), 0)
        cls._COUNT_CACHE[mtime_key[0]] = (mtime_key[1], count)
        return count

    @classmethod
    def scan_folder(cls, folder_path: str, recursive: bool = True, max_depth: int = 6, max_files: int = 0) -> list:
        """快速扫描文件夹 - 只列出文件，不读取内容（毫秒级）
        
        Args:
            folder_path: 文件夹路径
            recursive: 是否递归扫描
            max_depth: 最大递归深度（默认6层）
            max_files: 最大文件数量限制，0 表示不限制（默认）
        
        Returns:
            文章列表
        """
        articles = []
        folder = Path(folder_path)
        extensions = cls._ARTICLE_EXTS
        
        # 使用 os.scandir 比 Path.glob 快很多
        import os as _os
        seen = set()
        
        def scan(current_path, depth):
            if (max_files and len(articles) >= max_files) or depth > max_depth:
                return
                
            try:
                with _os.scandir(current_path) as entries:
                    for entry in entries:
                        if max_files and len(articles) >= max_files:
                            return
                        if entry.is_dir(follow_symlinks=False):
                            if recursive and depth < max_depth:
                                scan(entry.path, depth + 1)
                        elif entry.is_file(follow_symlinks=False):
                            ext = _os.path.splitext(entry.name)[1].lower()
                            if ext in extensions:
                                full_path = entry.path
                                if full_path not in seen:
                                    seen.add(full_path)
                                    title = _os.path.splitext(entry.name)[0]
                                    articles.append({
                                        "title": title,
                                        "source_file": full_path,
                                        "content": None,       # 延迟加载
                                        "_loaded": False,
                                    })
            except PermissionError:
                pass  # 跳过无权限访问的目录
            except OSError:
                pass  # 跳过其他系统错误
        
        scan(str(folder), 0)
        # 同步刷新计数缓存
        try:
            key = str(folder.resolve())
            mtime = folder.stat().st_mtime_ns
            cls._COUNT_CACHE[key] = (mtime, len(articles))
        except OSError:
            pass
        return articles
    
    @classmethod
    def load_content(cls, article: dict) -> dict:
        """懒加载文章内容（仅在发布时调用）"""
        if article.get("_loaded"):
            return article
        article["_loaded"] = True
        article.update(cls.parse_file(article["source_file"]))
        return article


# ============ 工具函数 ============

def format_time(timestamp=None):
    """格式化时间"""
    if timestamp is None:
        timestamp = time.time()
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

def select_from_list(items: list, key: str = "name", prompt: str = "请选择") -> Optional[dict]:
    """交互式列表选择"""
    if not items:
        print("  列表为空")
        return None
    
    for i, item in enumerate(items):
        name = item.get(key, str(item))
        extra = ""
        if "signature" in item:
            extra = f" [{item['signature']}]"
        if "url" in item:
            extra += f" - {item['url']}"
        print(f"  [{i+1}] {name}{extra}")
    
    try:
        choice = input(f"\n  {prompt} (1-{len(items)}, 或 q 退出): ").strip()
        if choice.lower() == 'q':
            return None
        idx = int(choice) - 1
        if 0 <= idx < len(items):
            return items[idx]
    except (ValueError, IndexError):
        pass
    
    print("  无效选择")
    return None

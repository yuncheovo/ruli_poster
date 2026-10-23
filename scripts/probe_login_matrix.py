# -*- coding: utf-8 -*-
"""独立站 / 合作站 / aicms 三类站点的登录与鉴权行为取证脚本。
仅做只读探测（GET + 一次未带凭据的 POST 试探），不提交任何业务数据。
"""
import json
import sys
import time

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# 抽样：独立站若干 + 合作站 + aicms
TARGETS = [
    ("independent", "nouhua", "https://admin.nouhua.com"),
    ("independent", "pangliu", "https://admin.pangliu.com"),
    ("independent", "zangpou", "https://admin.zangpou.com"),
    ("independent", "tikwigs", "https://admin.tikwigs.com"),
    ("independent", "lusswin", "https://admin.lusswin.com"),
    ("cooperation", "yeekang", "https://hz-admin-yeekang.ruli.com"),
    ("aicms", "aicms", "https://aicms-admin.ruli.com"),
]

out = []


def probe(kind, sig, base):
    row = {"kind": kind, "signature": sig, "base": base}
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*"})

    # 1) 登录页
    try:
        r = s.get(f"{base}/login", timeout=12, allow_redirects=True)
        txt = r.text or ""
        row["login_page"] = {
            "status": r.status_code,
            "len": len(txt),
            "content_type": r.headers.get("Content-Type", ""),
            "has_pwd_input": 'type="password"' in txt or "type='password'" in txt,
            "has_captcha": "captcha" in txt.lower(),
            "title": (txt.split("<title>")[1].split("</title>")[0].strip()
                      if "<title>" in txt else ""),
            "set_cookie": [c.name for c in r.cookies],
        }
    except Exception as e:
        row["login_page"] = {"error": str(e)[:120]}

    # 2) 直连 POST /login（不带任何真实凭据，仅探测守卫行为）
    for mode, payload in (("json", {"username": "", "password": "", "captcha": "", "remember": True}),):
        try:
            r = s.post(f"{base}/login", json=payload, timeout=12,
                       headers={"X-Requested-With": "XMLHttpRequest",
                                "Referer": f"{base}/login",
                                "Origin": base})
            row["post_login"] = {
                "status": r.status_code,
                "ct": r.headers.get("Content-Type", ""),
                "body": (r.text or "")[:160],
            }
        except Exception as e:
            row["post_login"] = {"error": str(e)[:120]}

    # 3) token 通道（伪造 token）
    try:
        r = s.get(f"{base}/login?token=FAKE_TOKEN_FOR_PROBE", timeout=12)
        body = (r.text or "")
        row["token_channel"] = {
            "status": r.status_code,
            "ct": r.headers.get("Content-Type", ""),
            "len": len(body),
            "body_head": body[:100],
            "is_plain_text": "text" in r.headers.get("Content-Type", "") and "<html" not in body.lower(),
        }
    except Exception as e:
        row["token_channel"] = {"error": str(e)[:120]}

    # 4) 未认证访问业务接口
    for ep in ("/article/category-tree", "/article/form"):
        try:
            r = s.get(f"{base}{ep}", timeout=12)
            row.setdefault("unauth_api", {})[ep] = {
                "status": r.status_code,
                "ct": r.headers.get("Content-Type", ""),
                "body_head": (r.text or "")[:120],
            }
        except Exception as e:
            row.setdefault("unauth_api", {})[ep] = {"error": str(e)[:80]}

    # 5) aicms 专属：take-new-token
    try:
        r = s.post(f"{base}/site/take-new-token", json={"token": "FAKE"}, timeout=12)
        row["take_new_token"] = {"status": r.status_code, "body_head": (r.text or "")[:160]}
    except Exception as e:
        row["take_new_token"] = {"error": str(e)[:120]}

    return row


if __name__ == "__main__":
    for kind, sig, base in TARGETS:
        print(f"[*] {kind:12s} {sig:10s} {base}")
        try:
            out.append(probe(kind, sig, base))
        except Exception as e:
            out.append({"kind": kind, "signature": sig, "base": base, "fatal": str(e)[:150]})
        time.sleep(0.5)
    with open("scripts/login_matrix_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n===== SUMMARY =====")
    for r in out:
        lp = r.get("login_page", {})
        pl = r.get("post_login", {})
        tc = r.get("token_channel", {})
        print(f"{r['signature']:10s} login={lp.get('status')} pwd={lp.get('has_pwd_input')} "
              f"cap={lp.get('has_captcha')} title={lp.get('title')!r}")
        print(f"           POST/login -> {pl.get('status')} {str(pl.get('body'))[:90]!r}")
        print(f"           token通道 -> {tc.get('status')} len={tc.get('len')} {str(tc.get('body_head'))[:70]!r}")
        print(f"           take-new-token -> {r.get('take_new_token')}")

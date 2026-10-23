# -*- coding: utf-8 -*-
"""
Ruli CMS 自动发文工具 - 命令行版
用法: python ruli_cli.py [选项]
"""
import sys
import os
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app_paths import app_dir, setup_runtime
from ruli_core import (
    RuliClient, CMSPoster, ArticleParser,
    format_time, select_from_list
)

setup_runtime()
CONFIG_FILE = app_dir() / "config.json"

def load_config():
    default_config = {
        "username": "",
        "password": "",
        "default_article_dir": "",
        "default_sites": [],
        "default_category": "",
        "center_admin_url": "https://center-admin.ruli.com",
        "default_interval": 5,   # 发布间隔（秒）
        "default_count": 0,       # 0=全部发布
        "article_api_endpoints": {
            "publish": "/content/article/add",
            "categories": "/content/category/list",
            "upload": "/site/upload",
        },
    }
    
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            for key, val in default_config.items():
                if key not in config:
                    config[key] = val
            return config
        except:
            pass
    return default_config

def save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# 每个站点的发布设置
class SiteSettings:
    def __init__(self, app: dict, default_category: str = "", default_interval: int = 5, default_count: int = 0):
        self.app = app
        self.category_id = default_category
        self.interval = default_interval
        self.count = default_count
        self.categories = []


def interactive_mode(config: dict, ctrl_url: str = None):
    """交互式模式"""
    print("\n" + "=" * 60)
    print("  Ruli CMS 自动发文工具 - 命令行版 v2.0")
    print("=" * 60)
    
    # ============ 登录 ============
    username = config.get("username", "")
    password = config.get("password", "")
    
    if not username:
        username = input("\n请输入控制中心手机号: ").strip()
    if not password:
        password = input("请输入控制中心密码: ").strip()
    
    print("\n正在登录控制中心...")
    client = RuliClient(username, password, admin_url=ctrl_url)
    
    if not client.login_ctrl():
        print("登录失败！")
        return
    
    print(f"  [OK] 登录成功")
    
    if not config.get("username") or not config.get("password"):
        save_pwd = input("\n是否保存登录凭证？(y/n): ").strip().lower()
        if save_pwd == 'y':
            config["username"] = username
            config["password"] = password
            save_config(config)
            print("  [OK] 已保存")
    
    # ============ 获取站点列表 ============
    print("\n正在获取站点列表...")
    apps = client.get_apps()
    
    if not apps:
        print("未找到任何站点！")
        return
    
    print(f"\n找到 {len(apps)} 个站点:")
    for i, app in enumerate(apps):
        sig = app.get("signature", "")
        name = app.get("name", "")
        cat = app.get("categoryText", "")
        print(f"  [{i+1:2d}] {name:12s} [{sig:12s}] {cat}")
    
    # ============ 选择站点 ============
    print("\n" + "-" * 40)
    apps_to_publish = []
    
    choice = input("请选择发布目标 (编号,多选逗号分隔, all=全部, q=退出): ").strip()
    
    if choice.lower() == 'q':
        return
    elif choice.lower() == 'all':
        apps_to_publish = apps
    else:
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
            for idx in indices:
                if 0 <= idx < len(apps):
                    apps_to_publish.append(apps[idx])
        except ValueError:
            print("无效输入")
            return
    
    if not apps_to_publish:
        print("未选择任何站点")
        return
    
    # ============ 全局设置 ============
    print("\n" + "-" * 40)
    print("全局发布设置（默认值，可为每个站点单独覆盖）:")
    
    default_interval = input(f"  发布间隔秒数 (默认{config.get('default_interval',5)}): ").strip()
    if not default_interval:
        default_interval = config.get("default_interval", 5)
    else:
        default_interval = int(default_interval)
    
    default_count = input(f"  每个站点发布篇数 (0=全部, 默认{config.get('default_count',0)}): ").strip()
    if not default_count:
        default_count = config.get("default_count", 0)
    else:
        default_count = int(default_count)
    
    # ============ 为每个站点单独设置 ============
    print("\n" + "-" * 40)
    print("各站点单独设置 (回车使用全局默认):")
    
    site_settings = []
    for app in apps_to_publish:
        name = app["name"]
        print(f"\n--- {name} [{app['signature']}] ---")
        
        interval = input(f"  发布间隔秒数 (默认{default_interval}): ").strip()
        if not interval:
            interval = default_interval
        else:
            interval = int(interval)
        
        count = input(f"  发布篇数 (0=全部, 默认{default_count}): ").strip()
        if not count:
            count = default_count
        else:
            count = int(count)
        
        ss = SiteSettings(app, interval=interval, count=count)
        site_settings.append(ss)
    
    # ============ 选择文章目录 ============
    print("\n" + "-" * 40)
    article_dir = config.get("default_article_dir", "")
    if not article_dir:
        article_dir = input("文章目录路径 (默认当前目录): ").strip()
    if not article_dir:
        article_dir = "."
    
    article_path = Path(article_dir)
    if not article_path.exists():
        print(f"目录不存在: {article_dir}")
        return
    
    print(f"\n正在扫描: {article_dir}")
    articles = ArticleParser.scan_folder(str(article_path))
    
    if not articles:
        print("未找到任何文章 (.md/.html/.txt)")
        return
    
    print(f"\n找到 {len(articles)} 篇文章:")
    for i, art in enumerate(articles):
        print(f"  [{i+1}] {art['title'][:50]}   ({Path(art['source_file']).name})")
    
    # ============ 选择文章 ============
    print("\n" + "-" * 40)
    choice = input("选择要发布的文章 (编号,多选, all=全部, q=退出): ").strip()
    
    articles_to_publish = []
    if choice.lower() == 'q':
        return
    elif choice.lower() == 'all':
        articles_to_publish = articles
    else:
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
            for idx in indices:
                if 0 <= idx < len(articles):
                    articles_to_publish.append(articles[idx])
        except ValueError:
            print("无效输入")
            return
    
    if not articles_to_publish:
        print("未选择任何文章")
        return
    
    # ============ 发布选项 ============
    print("\n" + "-" * 40)
    print("[1] 立即发布")
    print("[2] 定时发布")
    pub_choice = input("选择 (1/2): ").strip()
    
    schedule_time = None
    if pub_choice == "2":
        schedule_time = input("发布时间 (YYYY-MM-DD HH:MM:SS): ").strip()
    
    # ============ 确认 ============
    print("\n" + "=" * 60)
    print("发布确认")
    print("=" * 60)
    print(f"站点: {len(site_settings)} 个")
    for ss in site_settings:
        cnt = ss.count if ss.count > 0 else "全部"
        print(f"  - {ss.app['name']} (间隔{ss.interval}s, {cnt}篇)")
    print(f"文章: {len(articles_to_publish)} 篇")
    for art in articles_to_publish:
        print(f"  - {art['title'][:50]}")
    if schedule_time:
        print(f"定时: {schedule_time}")
    
    confirm = input("\n确认发布？(y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消")
        return
    
    # ============ 执行发布 ============
    print("\n" + "=" * 60)
    print("开始发布...")
    print("=" * 60)
    
    total_ok = 0
    total_fail = 0
    
    for ss in site_settings:
        sig = ss.app["signature"]
        name = ss.app["name"]
        
        print(f"\n--- {name} [{sig}] ---")
        
        cms_info = client.login_cms(sig)
        if not cms_info:
            print(f"  [!] 登录失败，跳过")
            total_fail += len(articles_to_publish)
            continue
        
        poster = CMSPoster(cms_info)
        print(f"  [OK] 已登录")
        
        # 限制每站发布数量
        arts_for_site = articles_to_publish[:ss.count] if ss.count > 0 else articles_to_publish
        if ss.count > 0 and ss.count < len(articles_to_publish):
            print(f"  限制: 只发布前 {ss.count} 篇")
        
        for idx, art in enumerate(arts_for_site):
            ArticleParser.load_content(art)
            title = art.get("title", "")
            print(f"  发布 [{idx+1}/{len(arts_for_site)}]: {title[:50]}")
            
            pub_data = {
                "title": title,
                "content": art.get("content", ""),
                "status": 1,
            }
            if ss.category_id:
                pub_data["category_id"] = ss.category_id
            if schedule_time:
                pub_data["published_at"] = schedule_time
            
            success = poster.publish_article(pub_data)
            
            if success:
                total_ok += 1
            else:
                total_fail += 1
            
            # 间隔
            if idx < len(arts_for_site) - 1 and ss.interval > 0:
                import time as t
                t.sleep(ss.interval)
    
    print("\n" + "=" * 60)
    print(f"完成! 成功: {total_ok}, 失败: {total_fail}")
    print("=" * 60)


def batch_mode(config: dict, article_dir: str, sites: list = None, schedule_time: str = None,
               interval: int = 5, count: int = 0, ctrl_url: str = None):
    """批处理模式"""
    username = config.get("username", "")
    password = config.get("password", "")
    
    if not username or not password:
        print("[!] 请先配置用户名和密码")
        return False
    
    client = RuliClient(username, password, admin_url=ctrl_url)
    if not client.login_ctrl():
        return False
    
    apps = client.get_apps()
    if sites:
        target_apps = [a for a in apps if a["signature"] in sites]
    else:
        target_apps = apps
    
    if not target_apps:
        print("[!] 未找到匹配的站点")
        return False
    
    articles = ArticleParser.scan_folder(article_dir)
    if not articles:
        print("[!] 未找到文章")
        return False
    
    total_ok = 0
    total_fail = 0
    
    for app in target_apps:
        cms_info = client.login_cms(app["signature"])
        if not cms_info:
            continue
        
        poster = CMSPoster(cms_info)
        arts_for_site = articles[:count] if count > 0 else articles
        
        for idx, art in enumerate(arts_for_site):
            ArticleParser.load_content(art)
            pub_data = {
                "title": art.get("title", ""),
                "content": art.get("content", ""),
                "status": 1,
            }
            if schedule_time:
                pub_data["published_at"] = schedule_time
            
            if poster.publish_article(pub_data):
                total_ok += 1
            else:
                total_fail += 1
            
            if idx < len(arts_for_site) - 1 and interval > 0:
                import time as t
                t.sleep(interval)
    
    print(f"\n完成: 成功 {total_ok}, 失败 {total_fail}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Ruli CMS 自动发文工具 v2.0")
    parser.add_argument("-d", "--dir", help="文章目录路径")
    parser.add_argument("-s", "--sites", help="目标站点signature，逗号分隔")
    parser.add_argument("-t", "--time", help="定时发布时间")
    parser.add_argument("-i", "--interval", type=int, default=5, help="发布间隔(秒)")
    parser.add_argument("-n", "--count", type=int, default=0, help="每站发布篇数(0=全部)")
    parser.add_argument("-u", "--url", help="控制中心地址 (默认 https://center-admin.ruli.com)")
    parser.add_argument("--batch", action="store_true", help="批处理模式（非交互）")
    parser.add_argument("--setup", action="store_true", help="配置向导")
    
    args = parser.parse_args()
    config = load_config()
    if args.url:
        config["center_admin_url"] = args.url
        save_config(config)

    if args.setup:
        print("配置向导")
        config["username"] = input("手机号: ").strip()
        config["password"] = input("密码: ").strip()
        save_config(config)
        print("已保存到 config.json")
        return
    
    if args.batch:
        sites = args.sites.split(",") if args.sites else config.get("default_sites", [])
        article_dir = args.dir or config.get("default_article_dir", "")
        if not article_dir:
            print("[!] 请指定文章目录 (-d)")
            return
        batch_mode(config, article_dir, sites, args.time, args.interval, args.count,
                   ctrl_url=config.get("center_admin_url"))
    else:
        interactive_mode(config, ctrl_url=config.get("center_admin_url"))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""整理 PyInstaller 输出为可分发目录"""
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

README_SLIM = """\
如丽 CMS 自动发文工具 v{ver}（标准版）

【运行】
  双击 启动.bat 或 RuliPoster.exe

【浏览器要求】
  使用您电脑上的 Microsoft Edge 或 Google Chrome（无需额外下载）
  Windows 10/11 一般已自带 Edge

【首次使用】
  1. 登录控制中心手机号/密码
  2. 设置文章目录、间隔、篇数
  3. 勾选站点后开始发布

【说明】
  - 配置保存在同目录 config.json
  - 日志在 logs 目录

版本: {ver}
"""

README_FULL = """\
如丽 CMS 自动发文工具 v{ver}（离线完整版）

【运行】
  双击 启动.bat 或 RuliPoster.exe

【说明】
  本版内置浏览器内核，无需本机安装 Chrome/Edge，体积较大。
  - 配置保存在同目录 config.json
  - 日志在 logs 目录
  - 请勿删除 ms-playwright 文件夹

版本: {ver}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ver", default="2.4.1")
    parser.add_argument("--mode", choices=("slim", "full"), default="slim")
    args = parser.parse_args()

    dist = ROOT / "dist" / "RuliPoster"
    suffix = "_full" if args.mode == "full" else ""
    out = ROOT / "release" / f"RuliPoster_v{args.ver}{suffix}"
    if not dist.is_dir():
        raise SystemExit(f"dist not found: {dist}")

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(dist, out)

    example = ROOT / "config.example.json"
    if example.exists():
        shutil.copy2(example, out / "config.example.json")
        cfg = out / "config.json"
        if not cfg.exists():
            shutil.copy2(example, cfg)

    (out / "启动.bat").write_text(
        '@echo off\r\n'
        'chcp 65001 >nul\r\n'
        'cd /d "%~dp0"\r\n'
        'start "" "%~dp0RuliPoster.exe"\r\n',
        encoding="utf-8-sig",
    )

    readme = README_FULL if args.mode == "full" else README_SLIM
    (out / "使用说明.txt").write_text(readme.format(ver=args.ver), encoding="utf-8-sig")

    exe = out / "RuliPoster.exe"
    has_browser = (out / "ms-playwright").is_dir()
    print(f"release: {out}")
    print(f"mode: {args.mode}")
    print(f"exe: {exe.exists()} ({exe.stat().st_size if exe.exists() else 0} bytes)")
    print(f"bundled browser: {has_browser}")


if __name__ == "__main__":
    main()

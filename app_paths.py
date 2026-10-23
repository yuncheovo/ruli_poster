# -*- coding: utf-8 -*-
"""应用路径 / 版本 / 打包环境初始化"""
import os
import sys
from pathlib import Path

APP_NAME = "如丽CMS自动发文"
APP_VERSION = "2.4.17"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """可写的应用根目录（exe 旁 / 源码目录）"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """可写的数据目录（用户主目录下固定位置，升级/换 exe 目录不丢配置）"""
    home = Path.home()
    d = home / "ruli_poster"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resource_dir() -> Path:
    """只读资源目录（打包后为 _MEIPASS）"""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def setup_runtime() -> Path:
    """打包环境初始化：工作目录、日志目录。浏览器优先用本机 Edge/Chrome。"""
    root = app_dir()
    os.chdir(root)

    # 仅当发行包自带 ms-playwright 时才指定（离线完整版）
    bundled = root / "ms-playwright"
    if bundled.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)

    for name in ("logs",):
        (root / name).mkdir(exist_ok=True)
    return root

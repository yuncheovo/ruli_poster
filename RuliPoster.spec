# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 如丽 CMS 自动发文 v2.4"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None
ROOT = Path(SPECPATH)

pw_datas, pw_binaries, pw_hidden = collect_all("playwright")
pil_datas = collect_data_files("PIL")

datas = [
    (str(ROOT / "logo.png"), "."),
    (str(ROOT / "config.example.json"), "."),
] + pw_datas + pil_datas

a = Analysis(
    [str(ROOT / "ruli_gui.py")],
    pathex=[str(ROOT)],
    binaries=pw_binaries,
    datas=datas,
    hiddenimports=pw_hidden + [
        "app_paths",
        "ruli_core",
        "ruli_cli",
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RuliPoster",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI 无黑窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "logo.ico") if (ROOT / "logo.ico").exists() else (
        str(ROOT / "logo.png") if (ROOT / "logo.png").exists() else None
    ),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RuliPoster",
)

# -*- coding: utf-8 -*-
"""
Ruli CMS 自动发文工具 - 图形界面版 v2.4
性能优化：Treeview 站点列表 + 文件数缓存 + 日志节流
"""
import sys, os, json, threading, time as _time, queue as _queue
from pathlib import Path
from datetime import datetime
from tkinter import (
    Tk, Frame, Label, Entry, Button, Checkbutton, IntVar, Toplevel,
    Text, Scrollbar, StringVar, BooleanVar, Spinbox, Menu,
    filedialog, ttk,
    END, VERTICAL, HORIZONTAL, RIGHT, LEFT, BOTH, Y, X,
    W, DISABLED, NORMAL, FLAT, GROOVE,
)
from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).parent))
from app_paths import APP_VERSION, app_dir, data_dir, resource_dir, setup_runtime
from ruli_core import RuliClient, CMSPoster, ArticleParser, format_time, check_browser_available

setup_runtime()
CONFIG_FILE = data_dir() / "config.json"
INVALID_CATEGORY_VALUES = {"", "加载中...", "获取失败", "无栏目/获取失败", "排队中..."}
LOG_MAX_LINES = 5000
LOG_FLUSH_MS = 120
# 主线程 UI 回调泵轮询间隔：后台线程只往队列放任务，主线程定时抽取执行，
# 彻底避免“后台线程直接调 Tk（Tcl 非线程安全）”导致的偶发卡死/死锁。
UI_PUMP_MS = 30
# 故障标记自动过期天数：超过这个天数的"发布故障/登录故障"标记自动失效并重新尝试。
# 目的：一次限流/WAF 拦截不应把站点永久废掉（曾出现一次误标记废掉 33 个站）。
FAILED_MARK_TTL_DAYS = 3


def load_config():
    _migrate_legacy_config()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"username": "", "password": "", "default_article_dir": "",
            "default_interval": 5, "default_count": 0, "default_category": "",
            "center_admin_url": "https://center-admin.ruli.com",
            "site_settings": {}}


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _migrate_legacy_config():
    """首次运行时，把 exe/源码旁旧的配置文件迁移到用户数据目录，避免账号密码丢失。"""
    import shutil
    for name in ("config.json", "site_categories.json", "category_cache.json"):
        legacy = app_dir() / name
        target = data_dir() / name
        if legacy.exists() and not target.exists():
            try:
                shutil.copy2(legacy, target)
            except Exception:
                pass


def extract_category_id(raw: str) -> str:
    """从栏目下拉值提取 ID，过滤占位文案。支持 '123 - 名称' 格式。"""
    raw = (raw or "").strip()
    if raw in INVALID_CATEGORY_VALUES:
        return ""
    if " - " in raw:
        raw = raw.split(" - ", 1)[0].strip()
    if raw in INVALID_CATEGORY_VALUES:
        return ""
    return raw


# ====== 现代化对话框（替代原生 messagebox）======

_DIALOG_THEME = {
    "success":  {"bg": "#10B981", "icon": "✓"},
    "info":     {"bg": "#3B82F6", "icon": "ⓘ"},
    "warning":  {"bg": "#F59E0B", "icon": "⚠"},
    "error":    {"bg": "#EF4444", "icon": "✕"},
    "question": {"bg": "#8B5CF6", "icon": "?"},
}


class ModernDialog:
    """扁平化风格对话框。无标题栏，居中显示，颜色按类型区分。"""

    def __init__(self, parent, title, message, type_="info", buttons=("确定",)):
        self.result = None
        self.parent = parent
        self.buttons = buttons
        cfg = _DIALOG_THEME.get(type_, _DIALOG_THEME["info"])
        bg = cfg["bg"]
        icon = cfg["icon"]

        top = Toplevel(parent)
        top.title(title)
        # 去掉 overrideredirect(True)：无边框窗口在 DPI 缩放/多屏下可能不显示，
        # 配合 wait_window() 会导致主线程永久卡死、软件点不动也关不掉。
        top.configure(bg="white")
        top.resizable(False, False)
        try:
            top.attributes("-topmost", False)
        except Exception:
            pass

        # 去掉阴影层（有系统标题栏时阴影会错位，直接用系统默认边框）
        body = Frame(top, bg="white", highlightbackground="#E5E7EB", highlightthickness=1)
        body.pack(fill=BOTH, expand=True)

        # 头部色条 + 图标 + 标题
        header = Frame(body, bg=bg, height=56)
        header.pack(fill=X)
        header.pack_propagate(False)
        Label(header, text=icon, font=("Segoe UI", 20, "bold"),
              bg=bg, fg="white").pack(side=LEFT, padx=(16, 8), pady=8)
        Label(header, text=title, font=("Segoe UI", 11, "bold"),
              bg=bg, fg="white", anchor=W).pack(side=LEFT, fill=X, expand=True, pady=8)

        # 消息
        content = Frame(body, bg="white")
        content.pack(fill=BOTH, expand=True, padx=22, pady=20)
        Label(content, text=message, font=("Segoe UI", 10),
              bg="white", fg="#374151", wraplength=400,
              justify=LEFT, anchor=W).pack(fill=X)

        # 按钮（右对齐，主操作高亮）
        btn_row = Frame(body, bg="white")
        btn_row.pack(fill=X, padx=22, pady=(0, 16))
        for i, txt in enumerate(buttons):
            primary = (i == len(buttons) - 1)
            normal_bg = bg if primary else "#F3F4F6"
            normal_fg = "white" if primary else "#374151"
            hover_bg = "#059669" if bg == "#10B981" else (
                       "#2563EB" if bg == "#3B82F6" else (
                       "#D97706" if bg == "#F59E0B" else (
                       "#DC2626" if bg == "#EF4444" else (
                       "#7C3AED" if bg == "#8B5CF6" else normal_bg))))
            hover_bg = bg if primary else "#E5E7EB"
            b = Button(
                btn_row, text=txt, font=("Segoe UI", 10, "bold"),
                bg=normal_bg, fg=normal_fg,
                activebackground=hover_bg, activeforeground=normal_fg,
                relief=FLAT, bd=0, padx=22, pady=8, cursor="hand2",
                command=lambda t=txt: self._done(top, t),
            )
            b.pack(side=RIGHT, padx=(6, 0))
            b.bind("<Enter>", lambda e, w=b, p=primary, nb=normal_bg, hb=hover_bg:
                   w.configure(bg=(hb if p else "#E5E7EB")))
            b.bind("<Leave>", lambda e, w=b, p=primary, nb=normal_bg:
                   w.configure(bg=nb))

        # 居中 + 模态
        top.update_idletasks()
        w = top.winfo_reqwidth()
        h = top.winfo_reqheight()
        if parent is not None:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
        else:
            px = py = 0
            pw = top.winfo_screenwidth()
            ph = top.winfo_screenheight()
        top.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 2}")
        top.transient(parent)
        # 不使用 grab_set()：它会在对话框被遮挡/最小化时抢走全部输入，
        # 配合 wait_window() 导致主线程死等、主窗口点不动也关不掉。

        # ESC 关闭
        top.bind("<Escape>", lambda e: self._done(top, buttons[0]))
        self._top = top

    def _done(self, top, value):
        self.result = value
        top.grab_release()
        top.destroy()

    def show(self):
        # 确保对话框一定置顶、可见、可交互，避免“最小化/多屏”场景下
        # 窗口不可见却仍 wait_window() 死等、导致主线程卡死。
        try:
            self._top.deiconify()
            self._top.lift()
            self._top.focus_force()
        except Exception:
            pass
        self._top.wait_window()
        # 兜底：万一窗口被异常销毁且未点按钮（如系统级关闭），返回第一个按钮的默认值
        if self.result is None:
            self.result = self.buttons[0]
        return self.result


def modern_info(parent, title, msg):
    return ModernDialog(parent, title, msg, "info").show()


def modern_success(parent, title, msg):
    return ModernDialog(parent, title, msg, "success").show()


def modern_warning(parent, title, msg):
    return ModernDialog(parent, title, msg, "warning").show()


def modern_error(parent, title, msg):
    return ModernDialog(parent, title, msg, "error").show()


def modern_confirm(parent, title, msg):
    """返回 True/False"""
    r = ModernDialog(parent, title, msg, "question", buttons=("取消", "确定")).show()
    return r == "确定"


def toast_info(parent, title, msg, duration_ms=6000):
    """非阻塞提示：弹出小窗展示结果，自动消失且可点击关闭。
    不调用 wait_window()、不使用 grab_set()，因此绝不阻塞主线程
    （用于“发布完成”等长任务结束通知，避免主窗口卡死/点不动/关不掉）。"""
    try:
        top = Toplevel(parent)
        top.title(title)
        top.resizable(False, False)
        top.configure(bg="white")
        body = Frame(top, bg="white", highlightbackground="#E5E7EB", highlightthickness=1)
        body.pack(fill=BOTH, expand=True)
        Label(body, text="✓", font=("Segoe UI", 18, "bold"), bg="white", fg="#10B981").pack(
            side=LEFT, padx=(16, 8), pady=14)
        Label(body, text=msg, font=("Segoe UI", 10), bg="white", fg="#374151",
              wraplength=360, justify=LEFT, anchor=W).pack(side=LEFT, fill=BOTH,
              expand=True, pady=14, padx=(0, 16))
        top.transient(parent)
        top.update_idletasks()
        w = top.winfo_reqwidth(); h = top.winfo_reqheight()
        if parent is not None:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
        else:
            px = py = 0; pw = top.winfo_screenwidth(); ph = top.winfo_screenheight()
        top.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 2}")
        try:
            top.deiconify(); top.lift(); top.focus_force()
        except Exception:
            pass
        top.bind("<Button-1>", lambda e: _safe_destroy(top))
        top.after(duration_ms, lambda: _safe_destroy(top))
    except Exception:
        pass


def _safe_destroy(top):
    try:
        if top.winfo_exists():
            top.destroy()
    except Exception:
        pass


def _short_path(path: str, maxlen: int = 36) -> str:
    if not path:
        return ""
    p = path.replace("\\", "/")
    if len(p) <= maxlen:
        return p
    return "…" + p[-(maxlen - 1):]


class RuliPosterGUI:
    def __init__(self):
        self.root = Tk()
        self.root.title(f"如丽 CMS v{APP_VERSION}")
        self.root.geometry("1200x850")
        self.root.minsize(1000, 700)

        lp = resource_dir() / "logo.png"
        if lp.exists():
            img = Image.open(lp)
            self.icon = ImageTk.PhotoImage(img)
            self.root.iconphoto(True, self.icon)

        self.config = load_config()
        self.admin_url_var = StringVar(
            value=self.config.get("center_admin_url", "https://center-admin.ruli.com")
        )
        self.client = None
        self.apps = []
        self.site_vars = {}  # sig -> settings vars / metadata
        self._selected_sig = None
        self._updating_editor = False
        self._publish_log_lines = []
        self._log_queue = []
        self._log_flush_scheduled = False
        self._log_file_path = None  # 开始发布时设置，日志追加写入
        # 线程安全 UI 派发队列：后台线程只 put，主线程 _ui_pump 抽取执行
        self._ui_queue = _queue.Queue()
        self._ui_running = True
        self._log_window = None
        self.log_text = None
        self._log_follow_var = BooleanVar(value=True)
        self._log_button_var = StringVar(value="查看日志")
        self._log_info_var = StringVar(value="暂无日志")
        self._publish_gate = threading.Event()
        self._publish_gate.set()
        self._publish_active = False
        self._progress_before_pause = ""
        self._count_job = 0
        self.login_failed_sites = set(self.config.get("login_failed_sites", []))
        # 登录成功但发文全部失败的站点（如 aicms 类无单篇发文接口、或 POST 被 CSRF/端点拦截）
        # 带时间戳：超过 FAILED_MARK_TTL_DAYS 自动失效重试，避免一次限流把站点永久废掉。
        self.publish_failed_sites = self._load_publish_failed_marks()

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        if self.config.get("username"):
            self.entry_username.insert(0, self.config["username"])
        if self.config.get("password"):
            self.entry_password.insert(0, self.config["password"])

        # 后台检测本机 Edge/Chrome 是否可用
        threading.Thread(target=self._check_browser_async, daemon=True).start()

    def _check_browser_async(self):
        ok, err = check_browser_available()
        if ok:
            self.ui(lambda: self.log("[OK] 本机浏览器可用 (Edge/Chrome)"))
        else:
            self.root.after(
                0,
                lambda: self.log(f"[!] 浏览器检测失败: {err[:80]} — 请安装 Edge 或 Chrome"),
            )

    def _on_close(self):
        # 释放可能正在暂停等待的后台发布线程。
        self._publish_gate.set()
        # 停止 UI 回调泵，避免窗口销毁后仍向已死 Tcl 投递。
        self._ui_running = False
        # 先关掉仍打开的模态/提示子窗口（如发布结束弹窗），避免它们卡住关闭。
        try:
            for w in list(self.root.winfo_children()):
                if isinstance(w, Toplevel) and w.winfo_exists():
                    try:
                        w.destroy()
                    except Exception:
                        pass
        except Exception:
            pass
        self._save_settings()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _save_settings(self):
        self.config["default_interval"] = self.g_interval.get()
        self.config["default_count"] = self.g_count.get()
        self.config["default_article_dir"] = self.article_dir_var.get()
        self.config["default_category"] = self.g_category.get()
        self.config["center_admin_url"] = self.admin_url_var.get().strip()
        self.config["cat_mode"] = self.cat_mode.get()
        self.config["username"] = self.entry_username.get().strip()
        self.config["password"] = self.entry_password.get().strip()
        ss = self.config.setdefault("site_settings", {})
        for sig, sv in self.site_vars.items():
            cat = extract_category_id(sv["category"].get())
            ss[sig] = {
                "folder": sv["folder"].get(),
                "category": cat,
                "interval": sv["interval"].get(),
                "count": sv["count"].get(),
            }
        save_config(self.config)

    def _save_login_failed(self):
        """持久化登录故障站点（按 signature），用于跨任务自动跳过。"""
        self.config["login_failed_sites"] = sorted(self.login_failed_sites)
        save_config(self.config)

    def _load_publish_failed_marks(self):
        """读取"发布故障"标记，兼容旧的 list 格式与新的 {sig: 时间戳} 格式。

        超过 FAILED_MARK_TTL_DAYS 的标记自动过期失效，下次发布会重新尝试，
        避免一次限流/WAF 拦截就把 30% 的站群永久废掉。
        """
        raw = self.config.get("publish_failed_sites") or []
        now = _time.time()
        ttl = FAILED_MARK_TTL_DAYS * 86400
        keep, expired = set(), []
        items = raw.items() if isinstance(raw, dict) else ((s, 0) for s in raw)
        for sig, ts in items:
            try:
                ts = float(ts)
            except (TypeError, ValueError):
                ts = 0.0
            # ts<=0 表示旧格式遗留（无时间），按"仍有效"处理，但下次标记时会补上时间
            if ts <= 0 or (now - ts) < ttl:
                keep.add(sig)
            else:
                expired.append(sig)
        if expired:
            marks = {k: v for k, v in (raw.items() if isinstance(raw, dict) else {})}
            for s in expired:
                marks.pop(s, None)
            self.config["publish_failed_sites"] = marks
            print(f"[i] 已自动过期 {len(expired)} 个发布故障标记（超过 {FAILED_MARK_TTL_DAYS} 天，本次重新尝试）")
        return keep

    def _save_publish_failed(self):
        """持久化"登录成功但发文失败"的站点（按 signature），用于跨任务自动跳过。"""
        old = self.config.get("publish_failed_sites")
        marks = dict(old) if isinstance(old, dict) else {}
        now = _time.time()
        for s in self.publish_failed_sites:
            # 已存在的时间戳保留（不刷新），新标记写入当前时间
            if not isinstance(marks.get(s), (int, float)):
                marks[s] = now
        for s in list(marks):
            if s not in self.publish_failed_sites:
                marks.pop(s, None)
        self.config["publish_failed_sites"] = marks
        save_config(self.config)

    def _clear_login_failed(self):
        """手动清除全部登录故障标记，下次发布会重新尝试登录这些站。"""
        n = len(self.login_failed_sites)
        self.login_failed_sites.clear()
        self._save_login_failed()
        modern_success(
            self.root, "已清除",
            f"已清除 {n} 个登录故障标记。\n下次发布将重新尝试登录这些站点。",
        )

    def _clear_publish_failed(self):
        """手动清除"登录成功但发文失败"标记，下次发布会重新尝试给这些站发文。"""
        n = len(self.publish_failed_sites)
        self.publish_failed_sites.clear()
        self._save_publish_failed()
        modern_success(
            self.root, "已清除",
            f"已清除 {n} 个发布故障标记。\n下次发布将重新尝试给这些站点发文。",
        )

    def _build_ui(self):
        # 顶部菜单栏
        menubar = Menu(self.root)
        tool_menu = Menu(menubar, tearoff=0)
        tool_menu.add_command(label="清除登录故障标记", command=self._clear_login_failed)
        tool_menu.add_command(label="清除发布故障标记", command=self._clear_publish_failed)
        menubar.add_cascade(label="工具", menu=tool_menu)
        self.root.config(menu=menubar)

        main = Frame(self.root, padx=10, pady=10)
        main.pack(fill=BOTH, expand=True)

        # ---- 登录 ----
        lf = Frame(main, relief="groove", bd=1, padx=10, pady=10)
        lf.pack(fill=X, pady=(0, 8))
        tr = Frame(lf)
        tr.grid(row=0, column=0, columnspan=8, sticky=W, pady=(0, 5))
        lp = resource_dir() / "logo.png"
        if lp.exists():
            li = Image.open(lp).resize((28, 28), Image.LANCZOS)
            self.ltk = ImageTk.PhotoImage(li)
            Label(tr, image=self.ltk).pack(side=LEFT, padx=(0, 8))
        Label(tr, text="如丽控制中心", font=("", 12, "bold")).pack(side=LEFT)
        Label(lf, text="手机号:").grid(row=1, column=0, sticky=W, padx=(0, 5))
        self.entry_username = Entry(lf, width=20)
        self.entry_username.grid(row=1, column=1, sticky=W, padx=(0, 12))
        Label(lf, text="密码:").grid(row=1, column=2, sticky=W, padx=(0, 5))
        self.entry_password = Entry(lf, width=25, show="*")
        self.entry_password.grid(row=1, column=3, sticky=W, padx=(0, 12))
        self.btn_login = Button(lf, text="登  录", command=self.do_login, bg="#409EFF", fg="white", width=10)
        self.btn_login.grid(row=1, column=4, padx=(0, 5))
        Button(lf, text="保存设置", command=self.do_save_settings).grid(row=1, column=5)
        self.lbl_status = Label(lf, text="未登录", fg="gray")
        self.lbl_status.grid(row=1, column=6, padx=(15, 0), sticky=W)

        # 控制中心地址（可配置，不再写死）
        Label(lf, text="控制中心:").grid(row=2, column=0, sticky=W, padx=(0, 5))
        Entry(lf, textvariable=self.admin_url_var, width=40).grid(
            row=2, column=1, columnspan=4, sticky=W, padx=(0, 12)
        )

        pane = ttk.PanedWindow(main, orient=HORIZONTAL)
        pane.pack(fill=BOTH, expand=True)

        # ==== 左面板 ====
        left = Frame(pane)
        pane.add(left, weight=30)

        sf = Frame(left, relief="groove", bd=1, padx=10, pady=10)
        sf.pack(fill=X, pady=(0, 8))
        Label(sf, text="全局发布设置", font=("", 11, "bold")).pack(anchor=W, pady=(0, 8))

        r1 = Frame(sf)
        r1.pack(fill=X, pady=2)
        Label(r1, text="间隔(秒):", width=10, anchor=W).pack(side=LEFT)
        self.g_interval = IntVar(value=self.config.get("default_interval", 5))
        Spinbox(r1, from_=0, to=300, textvariable=self.g_interval, width=6).pack(side=LEFT)

        r2 = Frame(sf)
        r2.pack(fill=X, pady=2)
        Label(r2, text="每站篇数:", width=10, anchor=W).pack(side=LEFT)
        self.g_count = IntVar(value=self.config.get("default_count", 0))
        Spinbox(r2, from_=0, to=999, textvariable=self.g_count, width=6).pack(side=LEFT, padx=(0, 5))
        Label(r2, text="(0=全部)", fg="gray").pack(side=LEFT)

        r3 = Frame(sf)
        r3.pack(fill=X, pady=2)
        Label(r3, text="文章目录:", width=10, anchor=W).pack(side=LEFT)
        self.article_dir_var = StringVar(value=self.config.get("default_article_dir", ""))
        Entry(r3, textvariable=self.article_dir_var).pack(side=LEFT, fill=X, expand=True, padx=(0, 3))
        Button(r3, text="浏览", command=self._browse_dir, width=5).pack(side=LEFT, padx=(0, 3))
        self.global_fc_lbl = Label(r3, text="", fg="#67C23A")
        self.global_fc_lbl.pack(side=LEFT)
        if self.article_dir_var.get():
            self.root.after(50, self._update_gfc)

        r5 = Frame(sf)
        r5.pack(fill=X, pady=2)
        Label(r5, text="栏目:", width=10, anchor=W).pack(side=LEFT)
        self.cat_mode = StringVar(value=self.config.get("cat_mode", "manual"))
        ttk.Radiobutton(r5, text="手动", variable=self.cat_mode, value="manual").pack(side=LEFT, padx=(0, 4))
        ttk.Radiobutton(r5, text="首个", variable=self.cat_mode, value="first").pack(side=LEFT, padx=(0, 4))
        ttk.Radiobutton(r5, text="随机", variable=self.cat_mode, value="random").pack(side=LEFT, padx=(0, 4))
        self.g_category = StringVar(value=self.config.get("default_category", ""))
        self.entry_category = Entry(r5, textvariable=self.g_category, width=10)
        self.entry_category.pack(side=LEFT, padx=(4, 0))
        Label(r5, text="ID", fg="gray", font=("", 8)).pack(side=LEFT)

        # 已写死：发布成功后一律删除源文件，避免重复使用
        Label(sf, text="发布成功后自动删除源文件（已固定开启）", fg="#E6A23C").pack(anchor=W, pady=(5, 0))

        r4 = Frame(sf)
        r4.pack(fill=X, pady=(5, 0))
        Button(r4, text="应用到各个站点", command=self._apply_to_all, bg="#67C23A", fg="white", width=16).pack(side=LEFT)

        pf = Frame(left, relief="groove", bd=1, padx=10, pady=10)
        pf.pack(fill=X, pady=(0, 8))
        Label(pf, text="发布方式", font=("", 11, "bold")).pack(anchor=W, pady=(0, 5))
        self.pub_mode = StringVar(value="now")
        ttk.Radiobutton(pf, text="立即发布", variable=self.pub_mode, value="now").pack(anchor=W)
        s2 = Frame(pf)
        s2.pack(fill=X, pady=(3, 0))
        ttk.Radiobutton(s2, text="定时发布", variable=self.pub_mode, value="schedule").pack(side=LEFT, padx=(0, 8))
        self.entry_schedule = Entry(s2, width=18)
        self.entry_schedule.pack(side=LEFT)
        self.entry_schedule.insert(0, format_time())

        ef = Frame(left, relief="groove", bd=1, padx=10, pady=10)
        ef.pack(fill=X, pady=(0, 8))
        Label(ef, text="执行模式", font=("", 11, "bold")).pack(anchor=W, pady=(0, 5))
        self.exec_mode = StringVar(value="concurrent")
        ttk.Radiobutton(ef, text="并发执行 (快, 多站同时登录+发文)", variable=self.exec_mode,
                        value="concurrent").pack(anchor=W)
        ttk.Radiobutton(ef, text="串行执行 (稳, 逐个站点依次处理)", variable=self.exec_mode,
                        value="sequential").pack(anchor=W)

        publish_actions = Frame(left)
        publish_actions.pack(fill=X)
        self.btn_publish = Button(publish_actions, text="▶  开始发布", command=self.do_publish,
                                  bg="#E6A23C", fg="white", font=("", 12, "bold"),
                                  height=2, state=DISABLED)
        self.btn_publish.pack(side=LEFT, fill=BOTH, expand=True)
        self.btn_pause = Button(publish_actions, text="暂停发布", command=self._toggle_pause,
                                width=11, state=DISABLED)
        self.btn_pause.pack(side=RIGHT, fill=Y, padx=(6, 0))

        self.progress_var = StringVar(value="")
        Label(left, textvariable=self.progress_var, fg="#409EFF", font=("", 9)).pack(pady=(5, 0))
        left_actions = Frame(left)
        left_actions.pack(pady=(8, 0))
        Button(left_actions, textvariable=self._log_button_var,
               command=self._show_log_window).pack(side=LEFT, padx=(0, 6))
        Button(left_actions, text="? 使用说明", command=self._show_help).pack(side=LEFT)

        # ==== 右面板：Treeview 站点列表 ====
        right = Frame(pane)
        pane.add(right, weight=70)
        Label(right, text="站点列表", font=("", 11, "bold")).pack(anchor=W, pady=(0, 5))

        btnr = Frame(right)
        btnr.pack(fill=X, pady=(0, 3))
        Button(btnr, text="全选", command=lambda: self._toggle_sites(True), width=5).pack(side=LEFT, padx=(0, 2))
        Button(btnr, text="全不选", command=lambda: self._toggle_sites(False), width=5).pack(side=LEFT, padx=(0, 2))
        Button(btnr, text="反选", command=self._invert_sites, width=5).pack(side=LEFT)
        Button(btnr, text="一键获取所有栏目", command=self._fetch_all_categories, width=15,
               bg="#67C23A", fg="white").pack(side=LEFT, padx=(10, 0))
        self.lbl_site_count = Label(btnr, text="", fg="gray")
        self.lbl_site_count.pack(side=RIGHT)

        tree_wrap = Frame(right, relief="sunken", bd=1)
        tree_wrap.pack(fill=BOTH, expand=True)
        cols = ("sel", "name", "folder", "category", "interval", "count", "files")
        self.site_tree = ttk.Treeview(
            tree_wrap, columns=cols, show="headings", selectmode="browse", height=18
        )
        self.site_tree.heading("sel", text="✓")
        self.site_tree.heading("name", text="站点")
        self.site_tree.heading("folder", text="文件夹")
        self.site_tree.heading("category", text="栏目")
        self.site_tree.heading("interval", text="间隔")
        self.site_tree.heading("count", text="篇数")
        self.site_tree.heading("files", text="文件")
        self.site_tree.column("sel", width=36, stretch=False, anchor="center")
        self.site_tree.column("name", width=160, stretch=True, anchor="w")
        self.site_tree.column("folder", width=220, stretch=True, anchor="w")
        self.site_tree.column("category", width=70, stretch=False, anchor="center")
        self.site_tree.column("interval", width=50, stretch=False, anchor="center")
        self.site_tree.column("count", width=50, stretch=False, anchor="center")
        self.site_tree.column("files", width=60, stretch=False, anchor="center")
        ysb = Scrollbar(tree_wrap, orient=VERTICAL, command=self.site_tree.yview)
        self.site_tree.configure(yscrollcommand=ysb.set)
        self.site_tree.pack(side=LEFT, fill=BOTH, expand=True)
        ysb.pack(side=RIGHT, fill=Y)
        self.site_tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.site_tree.bind("<Button-1>", self._on_tree_click)

        # 选中站点编辑条（仅 1 组控件，替代每站 12+ 控件）
        ed = Frame(right, relief="groove", bd=1, padx=8, pady=6)
        ed.pack(fill=X, pady=(6, 0))
        Label(ed, text="编辑选中站点", font=("", 9, "bold"), fg="#666").pack(anchor=W)
        self.edit_title = Label(ed, text="（点击上方列表选择站点）", fg="#999", anchor=W)
        self.edit_title.pack(fill=X, pady=(2, 4))

        er1 = Frame(ed)
        er1.pack(fill=X, pady=1)
        Label(er1, text="文件夹:", width=7, anchor=W).pack(side=LEFT)
        self.edit_folder = StringVar()
        Entry(er1, textvariable=self.edit_folder).pack(side=LEFT, fill=X, expand=True, padx=(0, 4))
        Button(er1, text="浏览", command=self._browse_selected, width=5).pack(side=LEFT)

        er2 = Frame(ed)
        er2.pack(fill=X, pady=1)
        Label(er2, text="栏目:", width=7, anchor=W).pack(side=LEFT)
        self.edit_category = StringVar()
        self.edit_cat_combo = ttk.Combobox(er2, textvariable=self.edit_category, width=18)
        self.edit_cat_combo.pack(side=LEFT, padx=(0, 4))
        Button(er2, text="获取栏目", command=self._fetch_selected_categories, width=8).pack(side=LEFT, padx=(0, 8))
        Label(er2, text="间隔").pack(side=LEFT)
        self.edit_interval = IntVar(value=5)
        Spinbox(er2, from_=0, to=300, textvariable=self.edit_interval, width=5).pack(side=LEFT, padx=(2, 8))
        Label(er2, text="篇数").pack(side=LEFT)
        self.edit_count = IntVar(value=0)
        Spinbox(er2, from_=0, to=999, textvariable=self.edit_count, width=5).pack(side=LEFT, padx=(2, 0))

        self.edit_folder.trace_add("write", lambda *_: self._sync_editor_to_site())
        self.edit_category.trace_add("write", lambda *_: self._sync_editor_to_site())
        self.edit_interval.trace_add("write", lambda *_: self._sync_editor_to_site())
        self.edit_count.trace_add("write", lambda *_: self._sync_editor_to_site())

    def _show_help(self):
        modern_info(
            self.root,
            "使用说明",
            "1. 登录控制中心\n"
            "2. 设置间隔、篇数、文章目录\n"
            "3. 「应用到各个站点」批量同步设置\n"
            "4. 点击列表勾选站点；下方可编辑选中站的文件夹/栏目\n"
            "5. 点击开始发布\n\n"
            "v2.4：站点列表改为表格，百站滚动更流畅\n"
            f"当前版本: {APP_VERSION}\n"
            "支持 .txt / .md / .html 格式",
        )

    # ========== 日志（节流） ==========
    def _show_log_window(self):
        if self._log_window is not None and self._log_window.winfo_exists():
            self._log_window.deiconify()
            self._log_window.lift()
            self._log_window.focus_force()
            return

        # 队列中的行已经存在于历史列表中；先落盘再重建窗口，避免重复显示。
        if self._log_queue:
            self._flush_logs()

        top = Toplevel(self.root)
        self._log_window = top
        top.title(f"运行日志 - 如丽 CMS v{APP_VERSION}")
        top.geometry("1000x650")
        top.minsize(700, 420)
        if hasattr(self, "icon"):
            top.iconphoto(True, self.icon)
        top.protocol("WM_DELETE_WINDOW", self._close_log_window)

        toolbar = Frame(top, padx=10, pady=8)
        toolbar.pack(fill=X)
        Label(toolbar, text="运行日志", font=("", 11, "bold")).pack(side=LEFT)
        Label(toolbar, textvariable=self._log_info_var, fg="#666").pack(side=LEFT, padx=(12, 0))
        Button(toolbar, text="打开日志目录", command=self._open_log_dir).pack(side=RIGHT)
        Button(toolbar, text="复制全部", command=self._copy_all_logs).pack(side=RIGHT, padx=(0, 6))
        Checkbutton(toolbar, text="自动滚动", variable=self._log_follow_var).pack(side=RIGHT, padx=(0, 10))

        text_frame = Frame(top, bg="#1e1e1e")
        text_frame.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        self.log_text = Text(
            text_frame, wrap="none", bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white", selectbackground="#264F78",
            font=("Consolas", 10), padx=8, pady=8, state=DISABLED,
        )
        ysb = Scrollbar(text_frame, orient=VERTICAL, command=self.log_text.yview)
        xsb = Scrollbar(text_frame, orient=HORIZONTAL, command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        text_frame.grid_rowconfigure(0, weight=1)
        text_frame.grid_columnconfigure(0, weight=1)

        if self._publish_log_lines:
            self.log_text.config(state=NORMAL)
            self.log_text.insert(END, "\n".join(self._publish_log_lines) + "\n")
            self.log_text.config(state=DISABLED)
            if self._log_follow_var.get():
                self.log_text.see(END)

        top.bind("<Control-a>", self._select_all_logs)
        top.bind("<Control-A>", self._select_all_logs)
        top.bind("<Escape>", lambda _event: self._close_log_window())
        self._update_log_info()

    def _close_log_window(self):
        if self._log_window is not None:
            try:
                self._log_window.destroy()
            except Exception:
                pass
        self._log_window = None
        self.log_text = None

    def _select_all_logs(self, _event=None):
        if self.log_text is not None:
            self.log_text.tag_add("sel", "1.0", "end-1c")
            self.log_text.mark_set("insert", "1.0")
            self.log_text.see("insert")
        return "break"

    def _copy_all_logs(self):
        content = "\n".join(self._publish_log_lines)
        if not content:
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.root.update_idletasks()
        return "break"

    def _open_log_dir(self):
        log_dir = Path(str(app_dir())) / "logs"
        log_dir.mkdir(exist_ok=True)
        try:
            os.startfile(str(log_dir))
        except Exception as exc:
            modern_warning(self._log_window or self.root, "提示", f"无法打开日志目录:\n{exc}")

    def _update_log_info(self):
        count = len(self._publish_log_lines)
        self._log_button_var.set(f"查看日志 ({count})" if count else "查看日志")
        if self._log_file_path:
            self._log_info_var.set(f"{count} 行  |  {_short_path(self._log_file_path, 70)}")
        else:
            self._log_info_var.set(f"{count} 行" if count else "暂无日志")

    def log(self, msg):
        ts = format_time()
        line = f"[{ts}] {msg}"
        self._publish_log_lines.append(line)
        if len(self._publish_log_lines) > LOG_MAX_LINES:
            del self._publish_log_lines[:-LOG_MAX_LINES]
        self._log_queue.append(line)
        self.ui(self._schedule_log_flush)

    def ui(self, fn):
        """线程安全的 UI 回调派发。

        后台线程（发布并发 worker 等）一律通过本方法把“要执行的 UI 操作”投递给主线程，
        绝不直接调用 Tk/Tcl（Tcl 非线程安全，直接跨线程调用偶发死锁会让主窗口点不动/关不掉）。
        主线程内调用则直接执行，避免不必要的延迟。
        """
        if threading.current_thread() is threading.main_thread():
            try:
                fn()
            except Exception:
                pass
        else:
            self._ui_queue.put(fn)

    def _ui_pump(self):
        """主线程循环：抽取并执行后台线程投递的 UI 回调。"""
        if not self._ui_running:
            return
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except _queue.Empty:
            pass
        if self._ui_running:
            try:
                self.root.after(UI_PUMP_MS, self._ui_pump)
            except Exception:
                pass

    def _schedule_log_flush(self):
        if self._log_flush_scheduled:
            return
        self._log_flush_scheduled = True
        self.root.after(LOG_FLUSH_MS, self._flush_logs)

    def _flush_logs(self):
        self._log_flush_scheduled = False
        if not self._log_queue:
            return
        batch = self._log_queue
        self._log_queue = []
        if self.log_text is not None and self.log_text.winfo_exists():
            self.log_text.config(state=NORMAL)
            self.log_text.insert(END, "\n".join(batch) + "\n")
            total = int(self.log_text.index("end-1c").split(".")[0])
            if total > LOG_MAX_LINES:
                self.log_text.delete("1.0", f"{total - LOG_MAX_LINES}.0")
            if self._log_follow_var.get():
                self.log_text.see(END)
            self.log_text.config(state=DISABLED)
        # 同步追加到日志文件（_log_file_path 在开始发布时由 run() 设置）
        if self._log_file_path:
            try:
                with open(self._log_file_path, "a", encoding="utf-8") as lf:
                    lf.write("\n".join(batch) + "\n")
                    lf.flush()
            except Exception:
                pass
        self._update_log_info()

    def set_status(self, t, c="black"):
        self.lbl_status.config(text=t, fg=c)

    def set_progress(self, t):
        if self._publish_active and not self._publish_gate.is_set():
            self._progress_before_pause = t
            self.progress_var.set("已暂停，点击“继续发布”恢复")
        else:
            self.progress_var.set(t)

    def _toggle_pause(self):
        if not self._publish_active:
            return
        if self._publish_gate.is_set():
            self._progress_before_pause = self.progress_var.get()
            self._publish_gate.clear()
            self.btn_pause.config(text="继续发布", bg="#67C23A", fg="white")
            self.progress_var.set("已暂停，点击“继续发布”恢复")
            self.log("[PAUSE] 发布已暂停")
        else:
            self._publish_gate.set()
            self.btn_pause.config(text="暂停发布", bg="SystemButtonFace", fg="black")
            self.progress_var.set(self._progress_before_pause)
            self.log("[RESUME] 发布已继续")

    def _wait_for_publish(self):
        """暂停时阻塞后台任务，继续后从当前位置恢复。"""
        self._publish_gate.wait()

    def _pause_aware_sleep(self, seconds):
        """只累计实际运行时间，暂停期间不消耗发布间隔。"""
        remaining = max(float(seconds), 0.0)
        while remaining > 0:
            self._wait_for_publish()
            step = min(0.2, remaining)
            started = _time.monotonic()
            _time.sleep(step)
            if self._publish_gate.is_set():
                remaining -= _time.monotonic() - started

    def _update_gfc(self):
        d = self.article_dir_var.get().strip()

        def work():
            n = 0
            try:
                if d and Path(d).exists():
                    n = ArticleParser.count_folder(d)
            except Exception:
                n = 0
            self.ui(lambda: self.global_fc_lbl.config(
                text=f"({n}篇)" if n else "", fg="#67C23A"
            ))

        threading.Thread(target=work, daemon=True).start()

    def _save_publish_log(self):
        # 日志已经在 _flush_logs 中实时写入文件，这里只返回路径
        return self._log_file_path or ""

    # ========== 登录 ==========
    def do_login(self):
        u = self.entry_username.get().strip()
        p = self.entry_password.get().strip()
        if not u or not p:
            modern_warning(self.root, "提示", "请输入手机号和密码")
            return
        self.btn_login.config(state=DISABLED, text="登录中...")
        self.log("正在登录控制中心...")

        def r():
            self.client = RuliClient(u, p, admin_url=self.admin_url_var.get().strip())
            if self.client.login_ctrl():
                self.ui(self._on_ok)
            else:
                self.ui(self._on_fail)

        threading.Thread(target=r, daemon=True).start()

    def _on_ok(self):
        self.set_status("已登录", "green")
        self.btn_login.config(state=NORMAL, text="重新登录")
        self.btn_publish.config(state=NORMAL)
        self._save_settings()
        self.log("[OK] 登录成功; 加载站点列表...")

        def load_apps():
            self.apps = self.client.get_apps()
            self.ui(self._on_apps_ok)

        threading.Thread(target=load_apps, daemon=True).start()

    def _on_fail(self):
        self.set_status("登录失败", "red")
        self.btn_login.config(state=NORMAL, text="登  录")
        self.log("[!] 登录失败")

    # ========== 站点列表（Treeview） ==========
    def _on_apps_ok(self):
        self.log(f"[OK] {len(self.apps)} 个站点")
        self._refresh_site_list()
        # 仅当全局目录有值且站点未配置文件夹时补齐，避免登录后再扫盘卡顿
        has_saved = any(
            (self.config.get("site_settings") or {}).get(a["signature"], {}).get("folder")
            for a in self.apps
        )
        if self.article_dir_var.get().strip() and not has_saved:
            self._apply_to_all()
        else:
            self._schedule_file_counts()

    def _row_values(self, sig):
        sv = self.site_vars[sig]
        return (
            "☑" if sv["var"].get() else "☐",
            f"{sv['name']} [{sig}]",
            _short_path(sv["folder"].get()),
            extract_category_id(sv["category"].get()) or "-",
            str(sv["interval"].get()),
            str(sv["count"].get()),
            sv.get("files_text", ""),
        )

    def _refresh_tree_row(self, sig):
        if sig in self.site_vars and self.site_tree.exists(sig):
            self.site_tree.item(sig, values=self._row_values(sig))

    def _refresh_site_list(self):
        gd = self.article_dir_var.get().strip()
        gc = extract_category_id(self.g_category.get())
        ss = self.config.get("site_settings", {})

        self.site_tree.delete(*self.site_tree.get_children())
        self.site_vars = {}
        self._selected_sig = None
        self.edit_title.config(text="（点击上方列表选择站点）", fg="#999")

        for app in self.apps:
            sig = app["signature"]
            name = app.get("name", "")
            saved = ss.get(sig, {})
            folder = saved.get("folder", gd) or gd
            cat = extract_category_id(str(saved.get("category", gc) or gc))
            cnt_val = saved.get("count", self.config.get("default_count", 0))
            ival_val = saved.get("interval", self.config.get("default_interval", 5))

            self.site_vars[sig] = {
                "var": BooleanVar(value=False),
                "interval": IntVar(value=ival_val),
                "count": IntVar(value=cnt_val),
                "folder": StringVar(value=folder),
                "category": StringVar(value=cat),
                "cat_values": [],
                "name": name,
                "files_text": "",
            }
            self.site_tree.insert("", END, iid=sig, values=self._row_values(sig))

        self.lbl_site_count.config(text=f"共 {len(self.apps)} 站")
        self._schedule_file_counts()

    def _schedule_file_counts(self):
        """后台按唯一路径统计文件数，避免 UI 线程卡死"""
        self._count_job += 1
        job = self._count_job
        snapshot = {sig: sv["folder"].get().strip() for sig, sv in self.site_vars.items()}

        def work():
            path_count = {}
            for path in set(p for p in snapshot.values() if p):
                if job != self._count_job:
                    return
                try:
                    path_count[path] = ArticleParser.count_folder(path) if Path(path).exists() else 0
                except Exception:
                    path_count[path] = 0

            updates = {}
            for sig, path in snapshot.items():
                n = path_count.get(path, 0)
                updates[sig] = f"{n}篇" if path and n else ("" if not path else "0篇")

            def apply():
                if job != self._count_job:
                    return
                for sig, text in updates.items():
                    if sig in self.site_vars:
                        self.site_vars[sig]["files_text"] = text
                        self._refresh_tree_row(sig)

            self.ui(apply)

        threading.Thread(target=work, daemon=True).start()

    def _on_tree_click(self, event):
        region = self.site_tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self.site_tree.identify_column(event.x)
        row = self.site_tree.identify_row(event.y)
        if not row:
            return
        # 点击勾选列切换选中
        if col == "#1":
            sv = self.site_vars.get(row)
            if sv:
                sv["var"].set(not sv["var"].get())
                self._refresh_tree_row(row)
            return "break"

    def _on_tree_select(self, _event=None):
        sel = self.site_tree.selection()
        if not sel:
            return
        self._load_editor(sel[0])

    def _load_editor(self, sig):
        sv = self.site_vars.get(sig)
        if not sv:
            return
        self._updating_editor = True
        self._selected_sig = sig
        self.edit_title.config(text=f"{sv['name']} [{sig}]", fg="#333")
        self.edit_folder.set(sv["folder"].get())
        self.edit_category.set(sv["category"].get())
        self.edit_interval.set(sv["interval"].get())
        self.edit_count.set(sv["count"].get())
        vals = sv.get("cat_values") or []
        self.edit_cat_combo.config(values=vals)
        self._updating_editor = False

    def _sync_editor_to_site(self):
        if self._updating_editor or not self._selected_sig:
            return
        sig = self._selected_sig
        sv = self.site_vars.get(sig)
        if not sv:
            return
        old_folder = sv["folder"].get()
        try:
            folder = self.edit_folder.get()
            cat = self.edit_category.get()
            iv = int(self.edit_interval.get())
            ct = int(self.edit_count.get())
        except Exception:
            return
        sv["folder"].set(folder)
        sv["category"].set(extract_category_id(cat) or cat)
        sv["interval"].set(iv)
        sv["count"].set(ct)
        self._refresh_tree_row(sig)
        if folder != old_folder:
            self._schedule_file_counts()

    def _browse_selected(self):
        if not self._selected_sig:
            modern_info(self.root, "提示", "请先在列表中选择一个站点")
            return
        d = filedialog.askdirectory(title="选择站点文章目录")
        if d:
            self.edit_folder.set(d)

    def _browse_dir(self):
        d = filedialog.askdirectory(title="选择文章目录")
        if d:
            self.article_dir_var.set(d)
            self._update_gfc()

    def _toggle_sites(self, checked):
        for sig, sv in self.site_vars.items():
            sv["var"].set(checked)
            self._refresh_tree_row(sig)

    def _invert_sites(self):
        for sig, sv in self.site_vars.items():
            sv["var"].set(not sv["var"].get())
            self._refresh_tree_row(sig)

    def _apply_to_all(self):
        iv = self.g_interval.get()
        ct = self.g_count.get()
        gd = self.article_dir_var.get().strip()
        gc = extract_category_id(self.g_category.get())
        for sig, sv in self.site_vars.items():
            sv["interval"].set(iv)
            sv["count"].set(ct)
            if gd:
                sv["folder"].set(gd)
            if gc:
                sv["category"].set(gc)
            self._refresh_tree_row(sig)
        if self._selected_sig:
            self._load_editor(self._selected_sig)
        self._schedule_file_counts()
        self.log(f"[OK] 已应用全局设置: 间隔{iv}s, 篇数{ct}, 栏目={gc or '无'}")

    def do_save_settings(self):
        self._save_settings()
        self.log("[OK] 设置已保存")
        modern_success(self.root, "成功", "已保存到 config.json")

    # ========== 栏目 ==========
    def _flatten_cats(self, cached):
        flat = []
        for c in cached:
            cid = c.get("id", c.get("category_id", ""))
            cname = c.get("name", c.get("title", ""))
            if cid:
                flat.append((str(cid), str(cname)))
            for child in c.get("children", c.get("child", [])) or []:
                cid2 = child.get("id", child.get("category_id", ""))
                if cid2:
                    flat.append((str(cid2), f"  {child.get('name', '')}"))
        return flat

    def _set_site_cat_values(self, sig, vals):
        sv = self.site_vars.get(sig)
        if not sv:
            return
        sv["cat_values"] = vals
        if vals and vals[0] not in INVALID_CATEGORY_VALUES:
            # 保留已选手动 ID；若为空可默认第一项显示名
            pass
        if self._selected_sig == sig:
            self.edit_cat_combo.config(values=vals)
        self._refresh_tree_row(sig)

    def _fetch_selected_categories(self):
        if not self._selected_sig:
            modern_info(self.root, "提示", "请先选择站点")
            return
        self._fetch_categories(self._selected_sig)

    def _fetch_categories(self, sig):
        if not self.client or not self.client.ctrl_token:
            modern_warning(self.root, "提示", "请先登录控制中心")
            return

        cached = CMSPoster.get_categories_cached(sig)
        if cached:
            flat = self._flatten_cats(cached)
            if flat:
                vals = [f"{cid} - {cn}" for cid, cn in flat]
                self._set_site_cat_values(sig, vals)
                self.log(f"[OK] {sig}: {len(vals)} 个栏目(缓存)")
                return

        cache_file = data_dir() / "site_categories.json"
        if cache_file.exists():
            try:
                cache = json.loads(cache_file.read_text(encoding="utf-8"))
                if sig in cache and cache[sig]:
                    vals = [f"{cid} - {cn}" for cid, cn in cache[sig]]
                    self._set_site_cat_values(sig, vals)
                    self.log(f"[OK] {sig}: {len(vals)} 个栏目(旧缓存)")
                    return
            except Exception:
                pass

        self.log(f"获取栏目: {sig} ...")
        if self._selected_sig == sig:
            self.edit_cat_combo.config(values=["加载中..."])

        def run():
            try:
                cats = self.client.fetch_cms_categories(sig)
                if cats:
                    vals = [f"{cid} - {cn}" for cid, cn in cats]
                    try:
                        cache_data = (
                            json.loads(cache_file.read_text(encoding="utf-8"))
                            if cache_file.exists()
                            else {}
                        )
                    except Exception:
                        cache_data = {}
                    cache_data[sig] = [[c[0], c[1]] for c in cats]
                    cache_file.write_text(
                        json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                else:
                    vals = ["无栏目/获取失败"]
                self.ui(lambda: self._set_site_cat_values(sig, vals))
                self.ui(lambda: self.log(f"[OK] {sig}: {len(cats)} 个栏目"))
            except Exception as e:
                self.ui(lambda: self._set_site_cat_values(sig, ["获取失败"]))
                self.ui(lambda: self.log(f"[!] 获取栏目失败: {e}"))

        threading.Thread(target=run, daemon=True).start()

    def _fetch_all_categories(self):
        if not self.client or not self.client.ctrl_token:
            modern_warning(self.root, "提示", "请先登录控制中心")
            return
        tasks = list(self.site_vars.keys())
        if not tasks:
            modern_info(self.root, "提示", "没有可获取的站点")
            return
        self.log(f"一键获取 {len(tasks)} 个站点的栏目...")

        # 先分拣：缓存命中的直接秒回，未命中的走批量登录
        cached_sigs = []
        need_login = []
        for sig in tasks:
            cached = CMSPoster.get_categories_cached(sig)
            if cached:
                cached_sigs.append((sig, cached))
            else:
                need_login.append(sig)

        # 缓存命中：直接刷新栏目（纯内存操作，不碰网络）
        for sig, cached in cached_sigs:
            flat = self._flatten_cats(cached)
            if flat:
                vals = [f"{cid} - {cn}" for cid, cn in flat]
                self.ui(lambda s=sig, v=vals: self._set_site_cat_values(s, v))
                self.ui(lambda s=sig, n=len(vals): self.log(f"  [OK] {s}: {n} 个栏目(缓存)"))

        if not need_login:
            self.ui(lambda: self.log(f"[OK] 栏目获取完成: 全部 {len(tasks)} 站(缓存)"))
            self.ui(lambda: self.lbl_site_count.config(text=f"栏目共 {len(tasks)} 站", fg="gray"))
            return

        self.log(f"  其中 {len(need_login)} 个站点需登录获取（批量并发，实时显示进度）...")

        def run():
            done = 0
            ok = 0
            lock = threading.Lock()

            def on_progress(sig, success):
                nonlocal done, ok
                with lock:
                    done += 1
                    if success:
                        ok += 1
                    marker = "[OK]" if success else "[FAIL]"
                    self.ui(lambda m=marker, s=sig: self.log(f"  {m} {s}: 登录{'成功' if success else '失败'}"))
                    self.root.after(
                        0,
                        lambda d=done, t=len(need_login): self.lbl_site_count.config(
                            text=f"栏目获取中 {d}/{t}", fg="#67C23A"
                        ),
                    )

            try:
                # 批量并发登录（单 context + 多页面，实时回调），拿到各站 cms_info
                results = self.client.batch_login_cms(
                    need_login, concurrency=5, progress_callback=on_progress
                )
            except Exception as e:
                self.ui(lambda e=e: self.log(f"[FAIL] 批量登录异常: {e}"))
                results = {s: None for s in need_login}

            # 登录成功后，用纯 HTTP 取栏目并刷新
            for sig in need_login:
                cms_info = results.get(sig)
                if not cms_info:
                    self.ui(lambda s=sig: self._set_site_cat_values(s, ["获取失败"]))
                    self.ui(lambda s=sig: self.log(f"  [FAIL] {s}: 登录失败, 无栏目"))
                    continue
                try:
                    poster = CMSPoster(cms_info)
                    cats = poster.get_categories_flat()  # get_categories 内部会自动写缓存
                    if cats:
                        vals = [f"{cid} - {cn}" for cid, cn in cats]
                        self.ui(lambda s=sig, v=vals: self._set_site_cat_values(s, v))
                        self.ui(lambda s=sig, n=len(vals): self.log(f"  [OK] {s}: {n} 个栏目"))
                    else:
                        self.ui(lambda s=sig: self._set_site_cat_values(s, ["获取失败"]))
                        self.ui(lambda s=sig: self.log(f"  [FAIL] {s}: 无栏目"))
                except Exception as e:
                    self.ui(lambda s=sig: self._set_site_cat_values(s, ["获取失败"]))
                    self.ui(lambda s=sig, e=e: self.log(f"  [FAIL] {s}: 取栏目异常 {e}"))

            total_ok = len(cached_sigs) + ok
            self.ui(lambda: self.log(f"[OK] 栏目获取完成: {total_ok}/{len(tasks)}"))
            self.root.after(
                0,
                lambda: self.lbl_site_count.config(text=f"栏目共 {total_ok}/{len(tasks)} 站", fg="gray"),
            )

        threading.Thread(target=run, daemon=True).start()

    # ========== 发布 ==========
    def _resolve_category(self, sig: str, site_category: str = "",
                          cat_mode: str = None, fallback: str = "") -> str:
        import random
        mode = cat_mode if cat_mode is not None else self.cat_mode.get()
        if mode == "manual":
            return extract_category_id(site_category) or extract_category_id(
                fallback or self.g_category.get()
            )
        cats = CMSPoster.get_categories_cached(sig)
        if not cats:
            return extract_category_id(site_category) or extract_category_id(
                fallback or self.g_category.get()
            )
        ids = []
        for c in cats:
            cid = c.get("id", c.get("category_id", ""))
            if cid:
                ids.append(str(cid))
            for child in c.get("children", c.get("child", [])) or []:
                cid2 = child.get("id", child.get("category_id", ""))
                if cid2:
                    ids.append(str(cid2))
        if not ids:
            return ""
        if mode == "first":
            return ids[0]
        if mode == "random":
            return random.choice(ids)
        return ""

    def do_publish(self):
        if not self.client or not self.client.ctrl_token:
            modern_warning(self.root, "提示", "请先登录")
            return

        selected = []
        for app in self.apps:
            sig = app["signature"]
            sv = self.site_vars.get(sig)
            if sv and sv["var"].get():
                d = sv["folder"].get().strip()
                if not d:
                    modern_warning(self.root, "提示", f"请为站点 {app['name']} 设置文件夹")
                    return
                if not Path(d).exists():
                    modern_warning(self.root, "提示", f"站点 {app['name']} 文件夹不存在")
                    return
                selected.append({
                    "app": app,
                    "interval": sv["interval"].get(),
                    "count": sv["count"].get(),
                    "folder": d,
                    "category": extract_category_id(sv["category"].get()),
                })
        if not selected:
            modern_warning(self.root, "提示", "请至少勾选一个站点")
            return

        st = None
        if self.pub_mode.get() == "schedule":
            st = self.entry_schedule.get().strip()
            if not st:
                modern_warning(self.root, "提示", "请输入定时发布时间")
                return

        do_delete = True  # 写死：发布后一律删除源文件
        is_concurrent = self.exec_mode.get() == "concurrent"
        cat_mode = self.cat_mode.get()
        global_cat = extract_category_id(self.g_category.get())

        msg = f"发布到 {len(selected)} 站:\n\n"
        for s in selected[:5]:
            cnt = s["count"] if s["count"] > 0 else "全部"
            msg += f"  {s['app']['name']} - {Path(s['folder']).name} ({cnt}篇, 间隔{s['interval']}s)\n"
        if len(selected) > 5:
            msg += f"  ... 等共 {len(selected)} 站\n"
        msg += f"\n模式: {'并发' if is_concurrent else '串行'}"
        if st:
            msg += f"\n定时: {st}"
        if do_delete:
            msg += "\n[!] 发布后删除源文件"
        failed_picked = [s["app"]["name"] for s in selected
                         if s["app"]["signature"] in self.login_failed_sites]
        if failed_picked:
            msg += (f"\n[提示] 将跳过 {len(failed_picked)} 个已知登录故障站: "
                    + "、".join(failed_picked[:10]))
            if len(failed_picked) > 10:
                msg += " 等"
            msg += "（工具→清除故障标记 可恢复重试）"
        publish_failed_picked = [s["app"]["name"] for s in selected
                                if s["app"]["signature"] in self.publish_failed_sites]
        if publish_failed_picked:
            msg += (f"\n[提示] 将跳过 {len(publish_failed_picked)} 个已知发布故障站(登录成功但发文失败): "
                    + "、".join(publish_failed_picked[:10]))
            if len(publish_failed_picked) > 10:
                msg += " 等"
            msg += "（工具→清除发布故障标记 可恢复重试）"
        if not modern_confirm(self.root, "确认发布", msg):
            return

        self._publish_log_lines.clear()
        self._log_queue.clear()
        if self.log_text is not None and self.log_text.winfo_exists():
            self.log_text.config(state=NORMAL)
            self.log_text.delete("1.0", END)
            self.log_text.config(state=DISABLED)

        # 先创建日志文件，确保本次发布的第一条消息也会写入磁盘。
        log_dir = Path(str(app_dir())) / "logs"
        log_dir.mkdir(exist_ok=True)
        self._log_file_path = str(log_dir / f"publish_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        self._update_log_info()

        self._publish_active = True
        self._publish_gate.set()
        self._progress_before_pause = ""
        self.btn_publish.config(state=DISABLED, text="发布中...")
        self.btn_pause.config(state=NORMAL, text="暂停发布", bg="SystemButtonFace", fg="black")
        self.log("=" * 50)
        self.log(f"发布 {len(selected)} 站 ({'并发' if is_concurrent else '串行'}) 删除={'是' if do_delete else '否'}")

        if is_concurrent:
            self._publish_concurrent(selected, st, do_delete, cat_mode, global_cat)
        else:
            self._publish_sequential(selected, st, do_delete, cat_mode, global_cat)

    def _publish_concurrent(self, selected, st, do_delete, cat_mode="manual", global_cat=""):
        total = len(selected)
        g_ok = [0]
        g_fail = [0]

        def run():
            plans = self._prepare_article_plans(selected)
            lr = {}
            sigs = [s["app"]["signature"] for s in selected]
            name_by_sig = {s["app"]["signature"]: s["app"]["name"] for s in selected}

            self.ui(lambda: self.log(f"阶段1: 批量登录 {total} 站..."))
            t0 = _time.time()
            done_cnt = [0]
            self._wait_for_publish()

            def on_login_progress(sig, ok):
                done_cnt[0] += 1
                nm = name_by_sig.get(sig, sig)
                tag = "OK" if ok else "FAIL"
                si = done_cnt[0]

                def ui():
                    self.set_progress(f"登录 [{si}/{total}] {nm}")
                    self.log(f"  [{tag}] [{si}/{total}] {nm}")

                self.ui(ui)

            try:
                lr = self.client.batch_login_cms(
                    sigs, concurrency=5, progress_callback=on_login_progress
                ) or {}
            except Exception as e:
                self.ui(lambda err=str(e): self.log(f"  [!] 批量登录异常: {err[:80]}"))
                lr = {}

            for sig in sigs:
                if lr.get(sig):
                    continue
                self._wait_for_publish()
                nm = name_by_sig.get(sig, sig)
                self.ui(lambda n=nm: self.log(f"  重试登录: {n}"))
                try:
                    ci = self.client.login_cms(sig)
                    if ci:
                        lr[sig] = ci
                except Exception:
                    pass

            self.root.after(
                0,
                lambda d=_time.time() - t0, o=sum(1 for v in lr.values() if v), t=total:
                self.log(f"  登录完成: {d:.1f}s ({o}/{t})"),
            )

            if not any(lr.values()):
                self.ui(lambda: self.log("  [!] 全部登录失败，退出"))
                self._finish_publish(0, sum(len(items) for items in plans.values()))
                return

            self._wait_for_publish()
            self.ui(lambda: self.log(f"阶段2: 并发发文 {total} 站..."))
            from concurrent.futures import ThreadPoolExecutor, wait
            import queue

            # 线程安全队列替代全局列表，攒够全部站才解锁
            result_q = queue.Queue()
            pending = len(selected)
            publish_failed_sigs = []

            def pub(s):
                a = s["app"]
                sig = a["signature"]
                nm = a["name"]
                iv = s["interval"]
                ci = lr.get(sig)
                tp = plans.get(sig, [])
                # 已知"登录成功但发文失败"的站：直接跳过
                if sig in self.publish_failed_sites:
                    line = f"[SKIP] {nm} - 发布故障"
                    self.ui(lambda l=line: self.log(l))
                    result_q.put((0, len(tp)))
                    return
                if not ci:
                    line = f"[SKIP] {nm}"
                    self.ui(lambda l=line: self.log(l))
                    result_q.put((0, len(tp)))
                    return
                o = f = 0
                f_biz = 0   # 业务拒绝（接口明确拒收）— 可认为站点确实有问题
                f_net = 0   # 网络/被拦截/限流 — 瞬时故障，不可永久标记
                try:
                    self._wait_for_publish()
                    if not tp:
                        line = f"[SKIP] {nm} - 空"
                        self.ui(lambda l=line: self.log(l))
                        result_q.put((0, 0))
                        return
                    line = f"  {nm}: {len(tp)}篇"
                    self.ui(lambda l=line: self.log(l))
                    p = CMSPoster(ci)
                    for j, art in enumerate(tp):
                        self._wait_for_publish()
                        # 单篇源文件不可用（被外部删除/占用/路径异常）时只跳过这一篇，
                        # 绝不让整个站点剩余的文章一起报废。
                        try:
                            ArticleParser.load_content(art)
                        except Exception as le:
                            f += 1
                            bn = os.path.basename(str(art.get("source_file", ""))) or str(le)
                            self.ui(lambda l=f"    [跳过] 源文件不可用: {bn}": self.log(l))
                            continue
                        t = art.get("title", "")[:80]
                        pd = {"title": t, "content": art.get("content", ""), "status": 1}
                        cid = self._resolve_category(
                            sig, s.get("category", ""), cat_mode=cat_mode, fallback=global_cat
                        )
                        if cid:
                            pd["category_id"] = cid
                        if st:
                            pd["published_at"] = st
                        if p.publish_article(pd):
                            o += 1
                            if do_delete:
                                self._safe_delete_source(art)
                        else:
                            f += 1
                            kind = getattr(p, "last_error_kind", "business")
                            if kind == "network":
                                f_net += 1
                            else:
                                f_biz += 1
                            err = getattr(p, "last_error", "")
                            fail_line = f"    [FAIL] {t} [{kind}] {err}"
                            self.ui(lambda l=fail_line: self.log(l))
                        if j < len(tp) - 1 and iv > 0:
                            self._pause_aware_sleep(iv)
                    sum_line = f"  >> {nm}: 成功{o}, 失败{f}"
                    self.ui(lambda l=sum_line: self.log(l))
                    # 登录成功但全部发文失败：仅当"接口明确拒绝"才永久标记；
                    # 纯网络/被拦截/限流属瞬时故障，绝不把站点废掉。
                    if ci and tp and o == 0 and f_biz > 0:
                        publish_failed_sigs.append(sig)
                    elif ci and tp and o == 0 and f_net > 0:
                        self.ui(lambda n=nm: self.log(
                            f"  [!] {n}: 全部失败但属网络/被拦截(瞬时)，不标记故障，下次仍会重试"))
                    result_q.put((o, f))
                except Exception as e:
                    # 单站异常不能阻塞汇总，保证 result_q 一定 put
                    err_line = f"  [ERROR] {nm}: {e}"
                    self.ui(lambda l=err_line: self.log(l))
                    result_q.put((o, f + max(len(tp) - o - f, 0)))

            def collect_and_finish():
                ok_total = 0
                fail_total = 0
                for _ in range(pending):
                    o, f = result_q.get()
                    ok_total += o
                    fail_total += f
                # 落盘"发布故障"标记（一次性保存，避免并发写配置）
                publish_failed_names = []
                if publish_failed_sigs:
                    for sig in set(publish_failed_sigs):
                        if sig not in self.publish_failed_sites:
                            self.publish_failed_sites.add(sig)
                            publish_failed_names.append(name_by_sig.get(sig, sig))
                    if publish_failed_sigs:
                        self._save_publish_failed()
                # 直接调用（已在主线程上下文，由 fut.result() 保证）
                self._finish_publish(ok_total, fail_total, [], [], [], publish_failed_names)

            with ThreadPoolExecutor(max_workers=min(8, total)) as ex:
                futs = [ex.submit(pub, s) for s in selected]
                # 等待所有 pub 任务完成后再汇总
                wait(futs)
                collect_and_finish()

        threading.Thread(target=run, daemon=True).start()

    def _publish_sequential(self, selected, st, do_delete, cat_mode="manual", global_cat=""):
        total = len(selected)
        g_ok = [0]
        g_fail = [0]

        def run():
            plans = self._prepare_article_plans(selected)
            skipped_failed, login_failed_names, empty_names, publish_failed_names = [], [], [], []
            for i, s in enumerate(selected):
                self._wait_for_publish()
                a = s["app"]
                sig = a["signature"]
                nm = a["name"]
                iv = s["interval"]
                tp = plans.get(sig, [])
                self.root.after(
                    0,
                    lambda n=nm, si=i + 1, t=total: (
                        self.log(f"\n--- [{si}/{t}] {n} ---"),
                        self.set_progress(f"站点 {si}/{t}: {n}"),
                    ),
                )
                # 已知登录故障站：直接跳过，不再浪费时间尝试登录
                if sig in self.login_failed_sites:
                    self.ui(lambda n=nm: self.log(
                        f"  [跳过] 已知登录故障: {n}（工具→清除故障标记后可重试）"))
                    skipped_failed.append(nm)
                    continue
                # 已知"登录成功但发文失败"的站：直接跳过，不再浪费时间尝试发文
                if sig in self.publish_failed_sites:
                    self.ui(lambda n=nm: self.log(
                        f"  [跳过] 已知发布故障: {n}（工具→清除发布故障标记后可重试）"))
                    publish_failed_names.append(nm)
                    continue
                if not tp:
                    self.ui(lambda n=nm: self.log(f"  [!] 空文件夹"))
                    empty_names.append(nm)
                    continue
                self.root.after(
                    0,
                    lambda n=nm, t=len(tp): self.log(f"  计划发布{t}篇"),
                )
                self.ui(lambda: self.set_progress(f"登录 {nm}..."))
                self._wait_for_publish()
                ci = self.client.login_cms(sig)
                if not ci:
                    self.ui(lambda n=nm: self.log(f"  [!] 登录失败"))
                    self.login_failed_sites.add(sig)
                    self._save_login_failed()
                    login_failed_names.append(nm)
                    g_fail[0] += len(tp)
                    continue
                # 登录成功：自愈，移除历史故障标记
                if sig in self.login_failed_sites:
                    self.login_failed_sites.discard(sig)
                    self._save_login_failed()
                p = CMSPoster(ci)
                o = f = 0
                f_biz = 0   # 业务拒绝
                f_net = 0   # 网络/被拦截/限流
                for j, art in enumerate(tp):
                    self._wait_for_publish()
                    # 单篇源文件不可用时只跳过这一篇，不让整站剩余文章报废。
                    try:
                        ArticleParser.load_content(art)
                    except Exception as le:
                        f += 1
                        g_fail[0] += 1
                        bn = os.path.basename(str(art.get("source_file", ""))) or str(le)
                        self.ui(lambda l=f"  [跳过] 源文件不可用: {bn}": self.log(l))
                        continue
                    t = art.get("title", "")[:80]
                    self.ui(lambda ti=t: self.set_progress(f"[{j + 1}/{len(tp)}] {ti}"))
                    pd = {"title": t, "content": art.get("content", ""), "status": 1}
                    cid = self._resolve_category(
                        sig, s.get("category", ""), cat_mode=cat_mode, fallback=global_cat
                    )
                    if cid:
                        pd["category_id"] = cid
                    if st:
                        pd["published_at"] = st
                    if p.publish_article(pd):
                        o += 1
                        g_ok[0] += 1
                        if do_delete:
                            self._safe_delete_source(art)
                    else:
                        f += 1
                        g_fail[0] += 1
                        kind = getattr(p, "last_error_kind", "business")
                        if kind == "network":
                            f_net += 1
                        else:
                            f_biz += 1
                        err = getattr(p, "last_error", "")
                        self.ui(lambda ti=t, k=kind, e=err: self.log(
                            f"  [FAIL] {ti} [{k}] {e}"))
                    if j < len(tp) - 1 and iv > 0:
                        self._pause_aware_sleep(iv)
                self.ui(lambda n=nm, o=o, f=f: self.log(f"  >> {n}: 成功{o}, 失败{f}"))
                # 登录成功但全部发文失败：仅"接口明确拒绝"才永久标记；
                # 纯网络/被拦截/限流是瞬时故障，不标记，下次照常重试。
                if ci and tp and o == 0 and f_biz > 0:
                    if sig not in self.publish_failed_sites:
                        self.publish_failed_sites.add(sig)
                        self._save_publish_failed()
                    publish_failed_names.append(nm)
                elif ci and tp and o == 0 and f_net > 0:
                    self.ui(lambda n=nm: self.log(
                        f"  [!] {n}: 全部失败但属网络/被拦截(瞬时)，不标记故障，下次仍会重试"))
            self._finish_publish(g_ok[0], g_fail[0], login_failed_names, empty_names, skipped_failed, publish_failed_names)

        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _source_key(source):
        return os.path.normcase(os.path.abspath(str(source)))

    def _prepare_article_plans(self, selected):
        """按站点分配互不重复的文章，避免共享目录下并发抢文件。"""
        plans = {}
        reserved = set()
        for s in selected:
            sig = s["app"]["signature"]
            arts = [
                art for art in ArticleParser.scan_folder(s["folder"])
                if self._source_key(art.get("source_file", "")) not in reserved
            ]
            count = s["count"]
            assigned = arts[:count] if count > 0 else arts
            plans[sig] = assigned
            reserved.update(
                self._source_key(art["source_file"])
                for art in assigned if art.get("source_file")
            )
        return plans

    def _safe_delete_source(self, art, nm=""):
        """发布成功后删除源文件，成功/失败都打日志（线程安全）"""
        src = art.get("source_file") if isinstance(art, dict) else art
        if not src:
            return False
        try:
            p = Path(src)
            if p.exists():
                p.unlink()
                self.ui(lambda: self.log(f"  [已删除] {p.name}"))
                return True
            return False
        except Exception as e:
            self.ui(lambda e=e, s=src: self.log(f"  [删除失败] {s}: {e}"))
            return False

    def _finish_publish(self, ok, fail, login_failed=None, empty=None, skipped=None, publish_failed=None):
        log_path = self._save_publish_log()
        self.root.after(
            0,
            lambda o=ok, f=fail, t=ok + fail, lp=log_path, lf=login_failed or [],
            em=empty or [], sk=skipped or [], pf=publish_failed or []:
            self._on_done(o, f, t, lp, lf, em, sk, pf),
        )

    def _on_done(self, ok, fail, total, log_path, login_failed, empty, skipped, publish_failed):
        self._publish_active = False
        self._publish_gate.set()
        self.btn_publish.config(state=NORMAL, text="▶  开始发布")
        self.btn_pause.config(state=DISABLED, text="暂停发布", bg="SystemButtonFace", fg="black")
        self.set_progress("")
        self.log("=" * 50)
        self.log(f"完成! 共{total}篇: 成功{ok}, 失败{fail}")
        if skipped:
            self.log(f"[汇总] 跳过已知登录故障 {len(skipped)} 站: " + "、".join(skipped)
                     + "（工具→清除故障标记后可重试）")
        if login_failed:
            self.log(f"[汇总] 本次登录失败 {len(login_failed)} 站: " + "、".join(login_failed))
        if publish_failed:
            self.log(f"[汇总] 登录成功但发文失败 {len(publish_failed)} 站: "
                     + "、".join(publish_failed)
                     + "（已自动标记，工具→清除发布故障标记后可重试）")
        if empty:
            self.log(f"[汇总] 空文件夹 {len(empty)} 站（已跳过，未放文章素材）")
        self.log(f"日志: {log_path}")
        self.set_status(f"成功:{ok} 失败:{fail}", "green" if fail == 0 else "orange")
        self._schedule_file_counts()
        # 用非阻塞 toast 代替阻塞式对话框：长发布结束后主线程不再被 wait_window 卡死
        toast_info(
            self.root,
            "发布完成",
            f"总计: {total} 篇\n成功: {ok} 篇\n失败: {fail} 篇\n\n"
            + (f"跳过登录故障: {len(skipped)} 站\n" if skipped else "")
            + (f"本次登录失败: {len(login_failed)} 站\n" if login_failed else "")
            + (f"发文失败(登录成功): {len(publish_failed)} 站\n" if publish_failed else "")
            + (f"空文件夹: {len(empty)} 站\n" if empty else "")
            + f"\n日志已保存:\n{log_path}",
        )

    def run(self):
        # 启动主线程 UI 回调泵（只在主线程挂一次，后台线程只往队列投递，杜绝跨线程 Tcl 死锁）
        try:
            self.root.after(UI_PUMP_MS, self._ui_pump)
        except Exception:
            pass
        self.root.mainloop()


def main():
    RuliPosterGUI().run()


if __name__ == "__main__":
    main()

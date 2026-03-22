"""
设计文件清理工具 v1.0
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os, threading, json, string, time
from pathlib import Path
from dataclasses import dataclass

try:
    from send2trash import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_VERSION = "1.0"
CONFIG_FILE = Path.home() / ".design_cleaner_config.json"
ZH = "Microsoft YaHei UI"

def font(size=13, weight="normal"):
    return ctk.CTkFont(family=ZH, size=size, weight=weight)

# ── 清理规则 ───────────────────────────────────────────────────────────────────
@dataclass
class Rule:
    app: str
    ext: str
    desc: str
    match_type: str
    safe: bool = True

RULES: list[Rule] = [
    Rule("SketchUp",    ".skb",        "SketchUp 自动备份",                      "suffix",            True),
    Rule("SketchUp",    ".skp.lock",   "SketchUp 文件锁（崩溃残留）",           "exact_suffix",      True),
    Rule("Rhino",       ".3dmbak",     "Rhino 上一版备份",                       "suffix",            True),
    Rule("Rhino",       ".rui.bak",    "Rhino 界面配置备份",                     "exact_suffix",      True),
    Rule("Rhino",       "RhinoCrash_", "Rhino 崩溃恢复文件",                     "prefix",            False),
    Rule("AutoCAD",     ".bak",        "AutoCAD 上一版备份（改 .dwg 可恢复）",   "suffix",            True),
    Rule("AutoCAD",     ".sv$",        "AutoCAD 定时自动保存",                   "suffix",            True),
    Rule("AutoCAD",     ".lck",        "AutoCAD 文件锁（崩溃残留）",             "suffix",            True),
    Rule("AutoCAD",     "ac$tmp_",     "AutoCAD 编辑临时文件",                   "prefix",            True),
    Rule("3ds Max",     ".xbk",        "3ds Max 增量备份",                       "suffix",            False),
    Rule("3ds Max",     "_vrayMesh",   "V-Ray 代理网格缓存",                     "prefix",            True),
    Rule("Photoshop",   ".psd~",       "Photoshop 上一版备份（非正稿 .psd）",    "exact_suffix",      False),
    Rule("Photoshop",   ".psb~",       "Photoshop 大文件备份（非正稿 .psb）",    "exact_suffix",      False),
    Rule("Illustrator", "~",           "Illustrator 临时文件（非正稿 .ai）",     "prefix_tilde_ai",   True),
    Rule("InDesign",    ".idlk",       "InDesign 文件锁（崩溃残留）",            "suffix",            True),
    Rule("InDesign",    "~",           "InDesign 临时文件（非正稿 .indd）",      "prefix_tilde_indd", True),
]

FIXED_DIRS: list[dict] = [
    {"app": "Rhino",       "desc": "Rhino 崩溃恢复目录",       "safe": False,
     "paths": [r"%APPDATA%\McNeel\Rhinoceros\8.0\AutoSave",
               r"%APPDATA%\McNeel\Rhinoceros\7.0\AutoSave",
               r"%APPDATA%\McNeel\Rhinoceros\6.0\AutoSave"]},
    {"app": "Rhino",       "desc": "Grasshopper 几何缓存",      "safe": True,
     "paths": [r"%LOCALAPPDATA%\McNeel\Rhinoceros\8.0\Grasshopper\Cache",
               r"%LOCALAPPDATA%\McNeel\Rhinoceros\7.0\Grasshopper\Cache"]},
    {"app": "AutoCAD",     "desc": "AutoCAD 临时文件",          "safe": True,
     "paths": [r"%LOCALAPPDATA%\Temp"]},
    {"app": "3ds Max",     "desc": "3ds Max 自动备份目录",      "safe": True,
     "paths": [r"%USERPROFILE%\Documents\3ds Max\autoback"]},
    {"app": "Lumion",      "desc": "Lumion 场景缓存",           "safe": True,
     "paths": [r"%LOCALAPPDATA%\Lumion 13\cache", r"%LOCALAPPDATA%\Lumion 12\cache",
               r"%LOCALAPPDATA%\Lumion 11\cache", r"%LOCALAPPDATA%\Lumion 10\cache"]},
    {"app": "D5 Render",   "desc": "D5 同步临时目录",           "safe": True,
     "paths": [r"%LOCALAPPDATA%\D5 Render\temp"]},
    {"app": "D5 Render",   "desc": "D5 素材缓存",               "safe": True,
     "paths": [r"%LOCALAPPDATA%\D5 Render\AssetCache"]},
    {"app": "Enscape",     "desc": "Enscape 场景缓存",          "safe": True,
     "paths": [r"%LOCALAPPDATA%\Enscape\Cache"]},
    {"app": "Enscape",     "desc": "Enscape 资产缓存",          "safe": True,
     "paths": [r"%LOCALAPPDATA%\Enscape\AssetCache"]},
    {"app": "Illustrator", "desc": "Illustrator 崩溃恢复目录", "safe": False,
     "paths": [r"%APPDATA%\Adobe\Adobe Illustrator 28 Settings\zh_CN\x64\Adobe Illustrator Recovery",
               r"%APPDATA%\Adobe\Adobe Illustrator 27 Settings\zh_CN\x64\Adobe Illustrator Recovery"]},
    {"app": "InDesign",    "desc": "InDesign 崩溃恢复目录",    "safe": False,
     "paths": [r"%APPDATA%\Adobe\InDesign\Version 19.0\zh_CN\InDesign Recovery",
               r"%APPDATA%\Adobe\InDesign\Version 18.0\zh_CN\InDesign Recovery"]},
]

SKIP_DIRS = {"Windows", "Program Files", "Program Files (x86)",
             "$Recycle.Bin", "System Volume Information", "ProgramData"}

@dataclass
class ScanResult:
    path: str
    app: str
    desc: str
    size: int
    safe: bool
    is_dir: bool = False

# ── 工具函数 ───────────────────────────────────────────────────────────────────
def get_drives():
    return [f"{l}:\\" for l in string.ascii_uppercase if os.path.exists(f"{l}:\\")]

def fmt_size(b):
    if b >= 1 << 30: return f"{b/(1<<30):.1f} GB"
    if b >= 1 << 20: return f"{b/(1<<20):.0f} MB"
    if b >= 1 << 10: return f"{b/(1<<10):.0f} KB"
    return f"{b} B"

def fmt_time(s):
    s = int(s)
    if s < 60:   return f"{s} 秒"
    if s < 3600: return f"{s//60} 分 {s%60} 秒"
    return f"{s//3600} 时 {(s%3600)//60} 分"

def get_size(path):
    try:
        p = Path(path)
        if p.is_file(): return p.stat().st_size
        if p.is_dir():  return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except: pass
    return 0

def match_rule(name, rule):
    n = name.lower()
    if rule.match_type == "suffix":            return n.endswith(rule.ext.lower())
    if rule.match_type == "exact_suffix":      return n.endswith(rule.ext.lower())
    if rule.match_type == "prefix":            return n.startswith(rule.ext.lower())
    if rule.match_type == "prefix_tilde_ai":   return n.startswith("~") and n.endswith(".ai")
    if rule.match_type == "prefix_tilde_indd": return n.startswith("~") and n.endswith(".indd")
    return False

def is_excluded(path, excl):
    p = Path(path).resolve()
    for e in excl:
        try:
            p.relative_to(Path(e).resolve())
            return True
        except ValueError: pass
    return False

def move_to_trash(path: str) -> bool:
    if HAS_SEND2TRASH:
        try:
            send2trash(path)
            return True
        except Exception:
            return False
    try:
        p = Path(path)
        if p.is_dir():
            import shutil; shutil.rmtree(path)
        else:
            p.unlink()
        return True
    except Exception:
        return False

# ── 主应用 ─────────────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"设计文件清理工具  v{APP_VERSION}")
        self.geometry("1080x720")
        self.minsize(900, 640)

        self.scan_results: list[ScanResult] = []
        self.result_vars:  dict[str, tk.BooleanVar] = {}
        self.scanning      = False
        self._stop_flag    = False
        self._pause_flag   = False
        self._pause_event  = threading.Event()
        self._pause_event.set()

        self.exclude_paths: list[str] = []
        self.drive_vars:   dict[str, tk.BooleanVar] = {}
        self.app_vars:     dict[str, tk.BooleanVar] = {}

        # 扫描状态（线程安全，用 lock 保护）
        self._lock          = threading.Lock()
        self._scan_start    = 0.0
        self._found_count   = 0
        self._drive_total   = 1
        self._scanned_bytes = 0
        self._current_drive = ""

        # UI 定时器 id（用于取消）
        self._ticker_id = None

        self._load_config()
        self._build()

        if not HAS_SEND2TRASH:
            self.after(500, self._warn_no_send2trash)

    def _warn_no_send2trash(self):
        messagebox.showwarning("提示",
            "未检测到 send2trash 库，移入回收站将改为直接删除（不可恢复）。\n\n"
            "建议运行：pip install send2trash")

    def _load_config(self):
        try:
            if CONFIG_FILE.exists():
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self.exclude_paths = cfg.get("exclude_paths", [])
        except: pass

    def _save_config(self):
        try:
            CONFIG_FILE.write_text(
                json.dumps({"exclude_paths": self.exclude_paths}, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except: pass

    # ── 布局 ───────────────────────────────────────────────────────────────────
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()

    # ── 侧边栏 ─────────────────────────────────────────────────────────────────
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=256, corner_radius=0,
                          fg_color=("gray91", "gray13"))
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(1, weight=1)

        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="ew", padx=18, pady=(20, 14))
        ctk.CTkLabel(logo, text="设计文件清理工具",
                     font=font(17, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(logo, text=f"v{APP_VERSION}  ·  自动清理设计软件备份与临时文件",
                     font=font(11), text_color=("gray50", "gray55"), anchor="w").pack(fill="x", pady=(4, 0))
        self._hline(sb, row=0, sticky="sew")

        scroll = ctk.CTkScrollableFrame(sb, fg_color="transparent",
                                         scrollbar_button_color=("gray75", "gray32"),
                                         scrollbar_button_hover_color=("gray60", "gray45"))
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        self._sec(scroll, "扫描驱动器")
        self._drive_box = ctk.CTkFrame(scroll, fg_color="transparent")
        self._drive_box.pack(fill="x", padx=18, pady=(0, 12))
        self._fill_drives()

        ctk.CTkFrame(scroll, height=1, fg_color=("gray80", "gray27")).pack(fill="x", padx=16, pady=4)

        self._sec(scroll, "扫描软件")
        self._app_box = ctk.CTkFrame(scroll, fg_color="transparent")
        self._app_box.pack(fill="x", padx=18, pady=(0, 14))
        self._fill_apps()

        self._hline(sb, row=2)

        excl = ctk.CTkFrame(sb, fg_color="transparent")
        excl.grid(row=3, column=0, sticky="ew", padx=16, pady=(10, 8))
        excl.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(excl, text="排除路径", font=font(12, "bold"),
                     text_color=("gray45", "gray55"), anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(excl, text="这些路径下的文件扫描时直接跳过",
                     font=font(11), text_color=("gray55", "gray50"), anchor="w").grid(
            row=1, column=0, sticky="w", pady=(2, 8))

        bf = ctk.CTkFrame(excl, fg_color="transparent")
        bf.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        bf.grid_columnconfigure(0, weight=1)
        bf.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(bf, text="添加路径", height=32, font=font(12),
                      command=self._add_excl).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(bf, text="清空", height=32, font=font(12),
                      fg_color=("gray76", "gray30"), text_color=("gray18", "gray88"),
                      hover_color=("gray62", "gray42"),
                      command=self._clear_excl).grid(row=0, column=1, padx=(4, 0), sticky="ew")

        self._excl_box = ctk.CTkFrame(excl, fg_color="transparent")
        self._excl_box.grid(row=3, column=0, sticky="ew")
        self._refresh_excl()

        self._hline(sb, row=4)

        self.scan_btn = ctk.CTkButton(sb, text="开始扫描", height=48,
                                       font=font(15, "bold"), command=self._toggle_scan)
        self.scan_btn.grid(row=5, column=0, sticky="ew", padx=14, pady=(14, 6))

        # 暂停按钮（初始隐藏）
        self.pause_btn = ctk.CTkButton(sb, text="暂停扫描", height=36,
                                        font=font(13),
                                        fg_color=("gray76", "gray30"),
                                        text_color=("gray18", "gray88"),
                                        hover_color=("gray62", "gray42"),
                                        command=self._toggle_pause)
        self.pause_btn.grid(row=6, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.pause_btn.grid_remove()   # 初始隐藏

    def _hline(self, parent, row=None, sticky="ew"):
        f = ctk.CTkFrame(parent, height=1, fg_color=("gray80", "gray27"))
        if row is not None:
            f.grid(row=row, column=0, sticky=sticky, padx=0)
        else:
            f.pack(fill="x", padx=16, pady=2)

    def _sec(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=font(12, "bold"),
                     text_color=("gray45", "gray55"), anchor="w").pack(
            fill="x", padx=18, pady=(14, 6))

    def _fill_drives(self):
        for w in self._drive_box.winfo_children(): w.destroy()
        for d in get_drives():
            var = tk.BooleanVar(value=True)
            self.drive_vars[d] = var
            ctk.CTkCheckBox(self._drive_box, text=d, variable=var,
                             font=font(13), height=30,
                             checkbox_width=17, checkbox_height=17).pack(anchor="w", pady=2)

    def _fill_apps(self):
        all_apps = sorted(set([r.app for r in RULES] + [e["app"] for e in FIXED_DIRS]))
        for a in all_apps:
            var = tk.BooleanVar(value=True)
            self.app_vars[a] = var
            ctk.CTkCheckBox(self._app_box, text=a, variable=var,
                             font=font(13), height=30,
                             checkbox_width=17, checkbox_height=17).pack(anchor="w", pady=2)

    # ── 主区域 ─────────────────────────────────────────────────────────────────
    def _build_main(self):
        main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)

        tb = ctk.CTkFrame(main, height=54, corner_radius=0, fg_color=("gray86", "gray18"))
        tb.grid(row=0, column=0, sticky="ew")
        tb.grid_columnconfigure(1, weight=1)
        tb.grid_propagate(False)

        stats = ctk.CTkFrame(tb, fg_color="transparent")
        stats.grid(row=0, column=0, padx=20, sticky="ns")
        self.lbl_files = ctk.CTkLabel(stats, text="—  个文件", font=font(14))
        self.lbl_files.grid(row=0, column=0, pady=14)
        ctk.CTkLabel(stats, text=" · ", font=font(14),
                     text_color=("gray55", "gray50")).grid(row=0, column=1)
        self.lbl_size = ctk.CTkLabel(stats, text="—", font=font(14))
        self.lbl_size.grid(row=0, column=2)

        rbf = ctk.CTkFrame(tb, fg_color="transparent")
        rbf.grid(row=0, column=2, padx=18, sticky="ns")
        for label, val in [("全选", True), ("全不选", False)]:
            ctk.CTkButton(rbf, text=label, width=70, height=34, font=font(13),
                          fg_color=("gray78", "gray32"), text_color=("gray18", "gray90"),
                          hover_color=("gray64", "gray42"),
                          command=lambda v=val: self._sel_all(v)).pack(side="left", padx=(0, 6))
        self.del_btn = ctk.CTkButton(
            rbf, text="移入回收站", width=118, height=34,
            font=font(13, "bold"),
            fg_color="#B83232", hover_color="#8C2222", text_color="#FFFFFF",
            state="disabled", command=self._confirm_delete)
        self.del_btn.pack(side="left", padx=(4, 0))

        # 状态栏（独立一行）
        status_bar = ctk.CTkFrame(main, height=28, corner_radius=0, fg_color=("gray91", "gray15"))
        status_bar.grid(row=1, column=0, sticky="ew")
        status_bar.grid_propagate(False)
        status_bar.grid_columnconfigure(0, weight=1)
        self.lbl_status = ctk.CTkLabel(status_bar, text="", font=font(12),
                                        text_color=("gray40", "gray58"), anchor="w")
        self.lbl_status.grid(row=0, column=0, sticky="ew", padx=18, pady=4)

        # 进度条
        self.prog = ctk.CTkProgressBar(main, height=3, corner_radius=0)
        self.prog.set(0)
        self.prog.grid(row=2, column=0, sticky="ew")
        self.prog.grid_remove()

        # 结果区
        self.result_area = ctk.CTkScrollableFrame(
            main, fg_color="transparent",
            scrollbar_button_color=("gray75", "gray38"),
            scrollbar_button_hover_color=("gray60", "gray50"))
        self.result_area.grid(row=3, column=0, sticky="nsew", padx=14, pady=(8, 12))
        self.result_area.grid_columnconfigure(0, weight=1)

        self._show_idle()

    def _show_idle(self):
        for w in self.result_area.winfo_children(): w.destroy()
        f = ctk.CTkFrame(self.result_area, fg_color="transparent")
        f.pack(expand=True, pady=80)
        ctk.CTkLabel(f, text="🔍", font=("Segoe UI Emoji", 40)).pack()
        ctk.CTkLabel(f, text="点击「开始扫描」检测垃圾文件",
                     font=font(15), text_color=("gray45", "gray55")).pack(pady=(14, 6))
        ctk.CTkLabel(f, text="在左侧选择驱动器、排除路径和要扫描的软件",
                     font=font(12), text_color=("gray58", "gray48")).pack()

    # ── 排除路径 ───────────────────────────────────────────────────────────────
    def _add_excl(self):
        path = filedialog.askdirectory(title="选择要排除的目录")
        if path and path not in self.exclude_paths:
            self.exclude_paths.append(path)
            self._save_config()
            self._refresh_excl()

    def _clear_excl(self):
        if not self.exclude_paths: return
        if messagebox.askyesno("确认", "清空所有排除路径？"):
            self.exclude_paths.clear()
            self._save_config()
            self._refresh_excl()

    def _refresh_excl(self):
        for w in self._excl_box.winfo_children(): w.destroy()
        if not self.exclude_paths:
            ctk.CTkLabel(self._excl_box, text="暂无排除路径",
                         font=font(11), text_color=("gray55", "gray50"),
                         anchor="w").pack(anchor="w", padx=4, pady=4)
            return
        for ep in self.exclude_paths:
            row = ctk.CTkFrame(self._excl_box, fg_color=("gray82", "gray22"), corner_radius=6)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=f"⛔  {Path(ep).name or ep}",
                         font=font(11), text_color=("gray25", "gray75"), anchor="w").pack(
                side="left", padx=10, pady=6)
            ctk.CTkButton(row, text="×", width=26, height=26, font=font(13),
                          fg_color="transparent", text_color=("gray40", "gray60"),
                          hover_color=("gray70", "gray35"),
                          command=lambda p=ep: self._rm_excl(p)).pack(side="right", padx=4)

    def _rm_excl(self, path):
        self.exclude_paths.remove(path)
        self._save_config()
        self._refresh_excl()

    # ── 扫描控制 ───────────────────────────────────────────────────────────────
    def _toggle_scan(self):
        if not self.scanning:
            self._start_scan()
        else:
            self._stop_scan()

    def _start_scan(self):
        drives   = [d for d, v in self.drive_vars.items() if v.get()]
        sel_apps = {a for a, v in self.app_vars.items() if v.get()}
        if not drives:   messagebox.showwarning("提示", "请至少勾选一个驱动器"); return
        if not sel_apps: messagebox.showwarning("提示", "请至少勾选一个软件");   return

        self.scanning       = True
        self._stop_flag     = False
        self._pause_flag    = False
        self._pause_event.set()
        self.scan_results.clear()
        self.result_vars.clear()

        with self._lock:
            self._scan_start    = time.time()
            self._found_count   = 0
            self._scanned_bytes = 0
            self._drive_total   = 1
            self._current_drive = drives[0] if drives else ""

        self.scan_btn.configure(text="停止扫描",
                                fg_color="#7A3300", hover_color="#5C2600",
                                text_color="#FFFFFF")
        self.pause_btn.configure(text="暂停扫描",
                                  fg_color=("gray76", "gray30"),
                                  text_color=("gray18", "gray88"))
        self.pause_btn.grid()

        self.del_btn.configure(state="disabled")
        self.lbl_files.configure(text="扫描中…")
        self.lbl_size.configure(text="")
        self.prog.configure(mode="indeterminate")
        self.prog.grid()
        self.prog.start()
        self._show_idle()

        # 启动独立的 UI 定时器，每 500ms 刷新一次状态栏
        self._start_ticker()

        threading.Thread(target=self._calc_total, args=(drives,), daemon=True).start()
        threading.Thread(target=self._scan_worker, args=(drives, sel_apps), daemon=True).start()

    def _stop_scan(self):
        self._stop_flag = True
        self._pause_event.set()   # 解除暂停让线程能检测到停止

    def _toggle_pause(self):
        if not self._pause_flag:
            self._pause_flag = True
            self._pause_event.clear()
            self.pause_btn.configure(text="继续扫描",
                                      fg_color=("#1A5E8A", "#1A5E8A"),
                                      text_color="#FFFFFF")
            self.prog.stop()
        else:
            self._pause_flag = False
            self._pause_event.set()
            self.pause_btn.configure(text="暂停扫描",
                                      fg_color=("gray76", "gray30"),
                                      text_color=("gray18", "gray88"))
            self.prog.configure(mode="indeterminate")
            self.prog.start()

    # ── UI 定时器（独立于扫描线程，暂停时也会运行）────────────────────────────
    def _start_ticker(self):
        self._tick()

    def _tick(self):
        """每 500ms 调用一次，更新状态栏，暂停时也持续运行"""
        if not self.scanning:
            return   # 扫描结束后停止

        with self._lock:
            found   = self._found_count
            elapsed = time.time() - self._scan_start
            bytes_s = self._scanned_bytes
            total   = self._drive_total
            drive   = self._current_drive
            paused  = self._pause_flag

        # 计算预计剩余时间
        ratio = min(bytes_s / total, 0.95) if total > 1 else 0

        if paused:
            # 暂停状态：持续显示已用时间和已发现数量，让用户知道工具还活着
            txt = f"已暂停  ·  已发现 {found} 个  ·  已用 {fmt_time(elapsed)}"
        elif elapsed < 2:
            txt = f"正在扫描 {drive}  ·  已发现 {found} 个"
        elif ratio > 0.005:
            rem = elapsed / ratio * (1 - ratio)
            txt = (f"正在扫描 {drive}  ·  已发现 {found} 个  ·  "
                   f"预计剩余 {fmt_time(rem)}")
        else:
            txt = (f"正在扫描 {drive}  ·  已发现 {found} 个  ·  "
                   f"已用 {fmt_time(elapsed)}")

        self.lbl_status.configure(text=txt)
        self.lbl_files.configure(text=f"{found}  个（扫描中）" if not paused else f"{found}  个（已暂停）")

        # 500ms 后再次调用
        self._ticker_id = self.after(500, self._tick)

    def _stop_ticker(self):
        if self._ticker_id is not None:
            self.after_cancel(self._ticker_id)
            self._ticker_id = None

    # ── 扫描线程 ───────────────────────────────────────────────────────────────
    def _calc_total(self, drives):
        total = 0
        for d in drives:
            try:
                import ctypes
                total_b = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    d, None, ctypes.byref(total_b), None)
                total += total_b.value
            except: pass
        with self._lock:
            self._drive_total = max(total, 1)

    def _scan_worker(self, drives, sel_apps):
        results = []
        active  = [r for r in RULES if r.app in sel_apps]

        for drive in drives:
            if self._stop_flag: break
            with self._lock:
                self._current_drive = drive

            try:
                for root, dirs, files in os.walk(drive, topdown=True):
                    if self._stop_flag: break
                    self._pause_event.wait()   # 暂停时在此阻塞
                    if self._stop_flag: break

                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

                    for fname in files:
                        if self._stop_flag: break
                        fpath = os.path.join(root, fname)
                        if is_excluded(fpath, self.exclude_paths): continue
                        for rule in active:
                            if match_rule(fname, rule):
                                sz = get_size(fpath)
                                results.append(ScanResult(
                                    fpath, rule.app, rule.desc, sz, rule.safe))
                                with self._lock:
                                    self._scanned_bytes += sz
                                    self._found_count   += 1
                                break
            except PermissionError:
                pass

        if not self._stop_flag:
            for entry in FIXED_DIRS:
                if entry["app"] not in sel_apps: continue
                for p in entry["paths"]:
                    rp = os.path.expandvars(p)
                    if os.path.exists(rp) and not is_excluded(rp, self.exclude_paths):
                        results.append(ScanResult(rp, entry["app"], entry["desc"],
                                                  get_size(rp), entry["safe"], is_dir=True))

        stopped = self._stop_flag
        self.after(0, self._scan_done, results, stopped)

    def _scan_done(self, results, was_stopped: bool):
        self._stop_ticker()
        self.scan_results = results
        self.scanning = False
        self.prog.stop()
        self.prog.grid_remove()
        self.pause_btn.grid_remove()

        # 恢复扫描按钮样式
        self.scan_btn.configure(text="开始扫描",
                                fg_color=("#1F6AA5", "#1F6AA5"),
                                hover_color=("#144870", "#144870"),
                                text_color="white")

        total   = sum(r.size for r in results)
        elapsed = time.time() - self._scan_start

        self.lbl_files.configure(text=f"{len(results)}  个文件")
        self.lbl_size.configure(text=fmt_size(total))

        if was_stopped:
            suffix = "  ·  以下为停止前扫描到的结果" if results else ""
            self.lbl_status.configure(
                text=f"已停止  ·  共发现 {len(results)} 项  ·  用时 {fmt_time(elapsed)}{suffix}")
        elif not results:
            self.lbl_status.configure(
                text=f"未发现可清理文件  ·  扫描用时 {fmt_time(elapsed)}")
            self._show_idle()
            return
        else:
            self.lbl_status.configure(
                text=f"扫描完成  ·  共 {len(results)} 项  ·  用时 {fmt_time(elapsed)}  ·  默认全部勾选，取消不想删的再点「移入回收站」")

        if results:
            self._render()
            self.del_btn.configure(state="normal")

    # ── 渲染结果 ───────────────────────────────────────────────────────────────
    def _render(self):
        for w in self.result_area.winfo_children(): w.destroy()
        self.result_vars.clear()
        by_app: dict[str, list[ScanResult]] = {}
        for r in self.scan_results:
            by_app.setdefault(r.app, []).append(r)
        for app, items in sorted(by_app.items()):
            self._render_group(app, items)

    def _render_group(self, app, items):
        grp_sz = sum(r.size for r in items)

        hd = ctk.CTkFrame(self.result_area, corner_radius=8, fg_color=("gray83", "gray21"))
        hd.pack(fill="x", pady=(10, 0))
        hd.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(hd, text=app, font=font(14, "bold"), anchor="w").grid(
            row=0, column=0, padx=16, pady=12, sticky="w")
        ctk.CTkLabel(hd, text=f"{len(items)} 个  ·  {fmt_size(grp_sz)}",
                     font=font(12), text_color=("gray45", "gray55"), anchor="w").grid(
            row=0, column=1, padx=6, sticky="w")

        gb = ctk.CTkFrame(hd, fg_color="transparent")
        gb.grid(row=0, column=2, padx=(0, 12), pady=10)
        for label, val in [("全选", True), ("取消", False)]:
            ctk.CTkButton(gb, text=label, width=56, height=28, font=font(12),
                          fg_color=("gray76", "gray34"), text_color=("gray15", "gray90"),
                          hover_color=("gray62", "gray44"),
                          command=lambda a=app, v=val: self._sel_group(a, v)).pack(side="left", padx=3)

        body = ctk.CTkFrame(self.result_area, corner_radius=0, fg_color=("gray96", "gray16"))
        body.pack(fill="x", pady=(0, 6))
        body.grid_columnconfigure(1, weight=1)

        for i, item in enumerate(items):
            bg = ("white", "gray14") if i % 2 == 0 else ("gray93", "gray17")
            row = ctk.CTkFrame(body, corner_radius=0, fg_color=bg)
            row.pack(fill="x")
            row.grid_columnconfigure(1, weight=1)

            var = tk.BooleanVar(value=True)
            self.result_vars[item.path] = var

            ctk.CTkCheckBox(row, text="", variable=var, width=36, height=46,
                             checkbox_width=16, checkbox_height=16).grid(
                row=0, column=0, rowspan=2, padx=(10, 2))
            ctk.CTkLabel(row, text=item.path,
                         font=ctk.CTkFont(family="Consolas", size=12),
                         anchor="w", text_color=("gray18", "gray85")).grid(
                row=0, column=1, padx=(4, 8), pady=(8, 2), sticky="ew")
            ctk.CTkLabel(row, text=item.desc, font=font(11),
                         text_color=("gray50", "gray55"), anchor="w").grid(
                row=1, column=1, padx=(4, 8), pady=(0, 8), sticky="ew")
            ctk.CTkLabel(row, text=fmt_size(item.size), font=font(12),
                         text_color=("gray48", "gray55"), width=78, anchor="e").grid(
                row=0, column=2, rowspan=2, padx=(0, 8))

            if item.safe:
                tb_bg, tb_fg, tb_txt = ("#D4EDDA", "#1A3A25"), ("#155724", "#4CAF50"), "安全"
            else:
                tb_bg, tb_fg, tb_txt = ("#FFF3CD", "#4A3800"), ("#856404", "#FFC107"), "需确认"
            ctk.CTkLabel(row, text=tb_txt, font=font(11),
                         fg_color=tb_bg, text_color=tb_fg,
                         corner_radius=4, width=52, height=22).grid(
                row=0, column=3, rowspan=2, padx=(0, 14))

    def _sel_all(self, val):
        for v in self.result_vars.values(): v.set(val)

    def _sel_group(self, app, val):
        for r in self.scan_results:
            if r.app == app and r.path in self.result_vars:
                self.result_vars[r.path].set(val)

    # ── 移入回收站 ─────────────────────────────────────────────────────────────
    def _confirm_delete(self):
        to_del = [r for r in self.scan_results
                  if r.path in self.result_vars and self.result_vars[r.path].get()]
        if not to_del:
            messagebox.showinfo("提示", "没有选中任何文件"); return

        total = sum(r.size for r in to_del)
        warns = [r for r in to_del if not r.safe]
        msg   = f"将 {len(to_del)} 个项目（共约 {fmt_size(total)}）移入回收站。\n"
        if warns:
            msg += f"\n其中 {len(warns)} 个「需确认」项目也在选中范围，请确认不再需要。\n"
        msg += "\n移入回收站后仍可恢复，确定继续？"

        if messagebox.askyesno("确认移入回收站", msg, icon="warning"):
            self._do_delete(to_del)

    def _do_delete(self, items):
        failed = []
        for r in items:
            if not move_to_trash(r.path):
                failed.append(r.path)

        done = {r.path for r in items} - set(failed)
        self.scan_results = [r for r in self.scan_results if r.path not in done]
        rem = sum(r.size for r in self.scan_results)
        self.lbl_files.configure(text=f"{len(self.scan_results)}  个文件")
        self.lbl_size.configure(text=fmt_size(rem))

        if self.scan_results:
            self._render()
            self.del_btn.configure(state="normal")
        else:
            self._show_idle()
            self.del_btn.configure(state="disabled")
            self.lbl_status.configure(text="清理完成，文件已全部移入回收站")

        if failed:
            messagebox.showerror("部分失败",
                f"{len(failed)} 个文件移入回收站失败（可能被软件占用）：\n\n" +
                "\n".join(f"• {p}" for p in failed[:10]))
        else:
            messagebox.showinfo("完成", f"已将 {len(items)} 个项目移入回收站")


if __name__ == "__main__":
    app = App()
    app.mainloop()

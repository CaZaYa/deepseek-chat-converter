"""图形界面。"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .core import (
    APP_NAME,
    APP_VERSION,
    FORMATS,
    PROJECT_URL,
    ConversionError,
    Options,
    convert,
    run_directory,
)

SETTINGS_PATH = Path(os.environ.get("APPDATA") or Path.home()) / "DeepSeek2Any" / "settings.json"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("720x600")
        self.minsize(660, 520)
        self._set_window_icon()

        self.zip_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.format_var = tk.StringVar(value="markdown")
        self.thinking_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="等待开始")

        self.events: queue.Queue = queue.Queue()
        self.running = False

        self._build()
        self.after(100, self._drain)

    def _set_window_icon(self):
        try:
            root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
            icon = root / "assets" / "icon.ico"
            if icon.is_file():
                self.iconbitmap(str(icon))
        except Exception:  # noqa: BLE001
            pass

    def _build(self):
        outer = ttk.Frame(self, padding=(18, 14, 18, 10))
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="DeepSeek 聊天记录 → 通用格式", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="可以导出 Markdown 文集、JSONL，或与 Cherry Studio 兼容的 ChatGPT JSON。",
            foreground="#666666",
        ).pack(anchor="w", pady=(2, 12))

        files = ttk.LabelFrame(outer, text=" 1. 选择文件 ", padding=(12, 8, 12, 10))
        files.pack(fill="x")

        ttk.Label(files, text="DeepSeek 导出包").grid(row=0, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.zip_var).grid(row=0, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(files, text="浏览…", command=self._pick_zip, width=8).grid(row=0, column=2, pady=3)

        ttk.Label(files, text="输出目录").grid(row=1, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.out_var).grid(row=1, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(files, text="浏览…", command=self._pick_out, width=8).grid(row=1, column=2, pady=3)

        ttk.Label(files, text="本次子文件夹").grid(row=2, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.name_var).grid(row=2, column=1, sticky="ew", padx=8, pady=3)
        ttk.Label(files, text="留空 = 按时间自动命名").grid(row=2, column=2, sticky="w")
        files.columnconfigure(1, weight=1)

        formats = ttk.LabelFrame(outer, text=" 2. 输出格式 ", padding=(12, 8, 12, 10))
        formats.pack(fill="x", pady=(10, 0))
        for index, (value, label) in enumerate(FORMATS):
            ttk.Radiobutton(formats, text=label, value=value, variable=self.format_var).grid(
                row=index, column=0, sticky="w", pady=1
            )
        ttk.Checkbutton(formats, text="包含思考过程（Markdown 中显示为粗体段落）", variable=self.thinking_var).grid(
            row=len(FORMATS), column=0, sticky="w", pady=(6, 0)
        )

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(12, 4))
        self.start_btn = ttk.Button(actions, text="开始转换", command=self._start)
        self.start_btn.pack(side="left")
        self.open_btn = ttk.Button(actions, text="打开输出目录", command=self._open_out, state="disabled")
        self.open_btn.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="关于", command=self._about).pack(side="right")
        ttk.Label(actions, textvariable=self.status_var, foreground="#666666").pack(side="right", padx=(0, 10))

        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(2, 10))

        log_frame = ttk.LabelFrame(outer, text=" 日志 ", padding=(8, 6, 8, 8))
        log_frame.pack(fill="both", expand=True)
        self.log_box = tk.Text(log_frame, height=9, wrap="word", state="disabled", relief="flat")
        self.log_box.pack(fill="both", expand=True)
        self._log(f"{APP_NAME} {APP_VERSION} 就绪")

    def _pick_zip(self):
        path = filedialog.askopenfilename(title="选择 DeepSeek 导出包", filetypes=[("ZIP 压缩包", "*.zip")])
        if path:
            self.zip_var.set(path)
            if not self.out_var.get():
                self.out_var.set(str(Path(path).with_suffix("")) + "_export")

    def _pick_out(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.out_var.set(path)

    def _open_out(self):
        target = self.out_var.get().strip()
        if target and Path(target).is_dir():
            os.startfile(target)  # noqa: S606

    def _log(self, message):
        self.events.put(("log", message))

    def _drain(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", payload + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "progress":
                    done, total = payload
                    self.progress["value"] = 100 if not total else done * 100 / total
                    self.status_var.set(f"处理中 {done}/{total}")
                elif kind == "done":
                    self._finish(payload)
                elif kind == "error":
                    self._fail(payload)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _start(self):
        if self.running:
            return
        zip_path, out_dir = self.zip_var.get().strip(), self.out_var.get().strip()
        if not zip_path or not Path(zip_path).is_file():
            messagebox.showwarning(APP_NAME, "请先选择 DeepSeek 导出包。")
            return
        if not out_dir:
            messagebox.showwarning(APP_NAME, "请先选择输出目录。")
            return

        try:
            target = run_directory(out_dir, self.name_var.get())
        except OSError as error:
            messagebox.showerror(APP_NAME, "无法创建输出文件夹：\n" + str(error))
            return

        self.running = True
        self.start_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.progress["value"] = 0
        self.status_var.set("准备中…")
        self._save_settings()

        options = Options(with_thinking=self.thinking_var.get())
        threading.Thread(
            target=self._worker,
            args=(zip_path, target, self.format_var.get(), options),
            daemon=True,
        ).start()

    def _worker(self, zip_path, out_dir, fmt, options):
        try:
            report = convert(
                zip_path, out_dir, fmt=fmt, options=options,
                log=self._log,
                progress=lambda done, total: self.events.put(("progress", (done, total))),
            )
            self.events.put(("done", report))
        except ConversionError as error:
            self.events.put(("error", error))
        except Exception as error:  # noqa: BLE001
            self.events.put(("error", error))

    def _finish(self, report):
        self.running = False
        self.start_btn.configure(state="normal")
        self.open_btn.configure(state="normal")
        self.progress["value"] = 100
        self.status_var.set("完成")
        if messagebox.askyesno(
            APP_NAME,
            f"会话 {report.conversations} 个\n消息 {report.messages} 条\n文件 {report.files} 个\n\n"
            f"输出目录：\n{report.output_dir}\n\n现在打开吗？",
        ):
            self._open_out()

    def _fail(self, error):
        self.running = False
        self.start_btn.configure(state="normal")
        self.status_var.set("失败")
        self._log(f"出错：{error}")
        messagebox.showerror(APP_NAME, f"转换失败：\n{error}")

    def _save_settings(self):
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(
                json.dumps({"mode": self.format_var.get(), "with_thinking": self.thinking_var.get()},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _about(self):
        messagebox.showinfo(
            f"关于 {APP_NAME}",
            f"{APP_NAME} {APP_VERSION}\n\n把 DeepSeek 导出包转换成通用聊天记录格式。\n"
            f"本地运行，不上传任何数据。\n\n{PROJECT_URL}",
        )


def main():
    App().mainloop()


if __name__ == "__main__":
    main()

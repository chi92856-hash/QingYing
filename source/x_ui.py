"""Preview X reply images; downloading always requires explicit selection."""
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from collector_ui import CollectorPanel


class XPanel(CollectorPanel):
    def __init__(self, parent, app, data_dir):
        ctk.CTkFrame.__init__(self, parent, fg_color='transparent')
        self.app = app; self.data_dir = data_dir; self.service = None
        self.items = []; self.selected = {}; self.cards = {}; self.thumbnails = {}
        self.all_var = tk.BooleanVar(value=False)
        self.summary = tk.StringVar(value='从主页帖子或评论中查找图片，获取后勾选下载。')
        self.source = tk.StringVar(value='主页图片')
        self.result_source = '主页图片'
        self.url = tk.StringVar()
        self.mode = tk.StringVar(value='图片'); self.batch_mode = '图片'
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(self, fg_color='transparent'); top.grid(row=0, column=0, sticky='ew', padx=14, pady=14)
        self.source_box = ctk.CTkOptionMenu(top, values=['主页图片', '评论图片'], variable=self.source, width=110)
        self.source_box.pack(side='left', padx=(0,6))
        self.entry = ctk.CTkEntry(top, textvariable=self.url, placeholder_text='粘贴 X 用户主页或帖子链接', height=34)
        self.entry.pack(side='left', fill='x', expand=True)
        self.login_btn = ctk.CTkButton(top, text='X 登录', width=85, command=self.login)
        self.login_btn.pack(side='left', padx=6)
        self.search_btn = ctk.CTkButton(top, text='获取图片', width=110, command=self.search)
        self.search_btn.pack(side='left')
        ctk.CTkLabel(self, textvariable=self.summary, anchor='w').grid(row=1, column=0, sticky='ew', padx=14)
        self.listbox = ctk.CTkScrollableFrame(self, fg_color='#F5F7FB')
        self.listbox.grid(row=2, column=0, sticky='nsew', padx=14, pady=8)
        bottom = ctk.CTkFrame(self, fg_color='transparent'); bottom.grid(row=3, column=0, sticky='ew', padx=14, pady=12)
        self.all_check = ctk.CTkCheckBox(bottom, text='全选', variable=self.all_var, command=self.select_all)
        self.all_check.pack(side='left')
        self.save_btn = ctk.CTkButton(bottom, text='下载所选（0）', command=self.download)
        self.save_btn.pack(side='right')
        self.controls = [self.entry, self.source_box, self.login_btn, self.search_btn, self.all_check]
        self._render()

    def get_service(self):
        if self.service is None:
            from x_support import XService
            if getattr(self.app, 'x_service', None) is None:
                self.app.x_service = XService(self.data_dir, self.app.emit_log, self.app.emit_progress)
            self.service = self.app.x_service
        return self.service

    def _selection(self):
        count = sum(v.get() for v in self.selected.values())
        self.save_btn.configure(text=f'下载所选（{count}）', state='normal' if count and not self.app.busy else 'disabled')

    def search(self):
        if self.app.busy: return
        from x_support import post_url, profile_url
        source = self.source.get()
        try: url, _ = (profile_url if source == '主页图片' else post_url)(self.url.get())
        except ValueError as error:
            messagebox.showinfo('检查链接', str(error)); return
        self.items = []; self._render()
        self.result_source = source
        self.summary.set('正在从主页帖子逐条查找图片，纯文字帖子会继续跳过，最多 90 秒…' if source == '主页图片' else '正在获取评论图片，完成后可自行勾选下载…')
        def job():
            last = ()
            def publish(found):
                nonlocal last
                checked = len(getattr(service.browser, 'profile_posts', ())) if source == '主页图片' else 0
                detail = f'已检查 {checked} 条主页帖子，' if source == '主页图片' else ''
                self.app.emit_progress(0, f'正在获取 X {source}，{detail}已找到 {len(found)} 张图片')
                signature = tuple(item.identifier for item in found)
                if signature != last:
                    last = signature
                    self.app.events.put(('x_batch', list(found)))
            try:
                service = self.get_service()
                fetch = service.profile if source == '主页图片' else service.search
                items = fetch(url, self.app.cancel, publish)
            except Exception as error:
                self.app.events.put(('x_error', str(error)))
                raise
            self.app.events.put(('x_batch', items))
            self.get_service().thumbnails(items, lambda key, data: self.app.events.put(('x_thumbnail', (key, data))))
            return f'获取完成：找到 {len(items)} 张 X {source}，请自行勾选下载。'
        self.app.run_job(job)

    def handle_batch(self, items):
        self.items = items
        self.summary.set(f'{self.result_source}：找到 {len(items)} 张，请勾选后下载。仅包含本次网页已加载的内容，最多 200 张。')
        self._render()

    def handle_error(self, message):
        self.summary.set('获取已停止：' + message)

    def download(self):
        if self.app.busy: return
        items = [item for item in self.items if self.selected[item.identifier].get()]
        if not items: return
        try: folder = self.app.output_dir()
        except Exception as error:
            messagebox.showerror('保存位置', str(error)); return
        def job():
            saved, failed, skipped = self.get_service().download(items, folder, '图片', False, self.app.cancel)
            self.app.events.put(('x_saved', (saved, failed, skipped)))
            return f'X 图片保存完成：成功 {len(saved)} 张，失败 {len(failed)} 张，重复跳过 {skipped} 张。'
        self.app.run_job(job)

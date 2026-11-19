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
        self.summary = tk.StringVar(value='粘贴 X 作品链接，解析图片和视频，勾选后保存。')
        self.source = tk.StringVar(value='作品链接')
        self.result_source = '作品链接'
        self.url = tk.StringVar()
        self.mode = tk.StringVar(value='图片和视频'); self.batch_mode = '图片和视频'
        self.result_mode = '图片和视频'
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(self, fg_color='transparent'); top.grid(row=0, column=0, sticky='ew', padx=14, pady=14)
        self.source_box = ctk.CTkOptionMenu(top, values=['作品链接', '主页作品', '评论作品'], variable=self.source, width=110)
        self.source_box.pack(side='left', padx=(0,6))
        self.mode_box = ctk.CTkOptionMenu(top, values=['图片', '视频', '图片和视频'], variable=self.mode, width=100)
        self.mode_box.pack(side='left', padx=(0,6))
        self.entry = ctk.CTkEntry(top, textvariable=self.url, placeholder_text='粘贴 X 链接，多条作品用空格分隔', height=34)
        self.entry.pack(side='left', fill='x', expand=True)
        self.login_btn = ctk.CTkButton(top, text='X 登录', width=85, command=self.login)
        self.login_btn.pack(side='left', padx=6)
        self.search_btn = ctk.CTkButton(top, text='获取作品', width=110, command=self.search)
        self.search_btn.pack(side='left')
        self.next_btn = ctk.CTkButton(top, text='继续采集', width=90, command=self.continue_search)
        self.next_btn.pack(side='left', padx=(6,0))
        ctk.CTkLabel(self, textvariable=self.summary, anchor='w').grid(row=1, column=0, sticky='ew', padx=14)
        self.listbox = ctk.CTkScrollableFrame(self, fg_color='#F5F7FB')
        self.listbox.grid(row=2, column=0, sticky='nsew', padx=14, pady=8)
        bottom = ctk.CTkFrame(self, fg_color='transparent'); bottom.grid(row=3, column=0, sticky='ew', padx=14, pady=12)
        self.all_check = ctk.CTkCheckBox(bottom, text='全选', variable=self.all_var, command=self.select_all)
        self.all_check.pack(side='left')
        self.save_btn = ctk.CTkButton(bottom, text='下载所选（0）', command=self.download)
        self.save_btn.pack(side='right')
        self.controls = [self.entry, self.source_box, self.mode_box, self.login_btn, self.search_btn, self.next_btn, self.all_check]
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

    def continue_search(self):
        self.search(resume=True)

    def search(self, resume=False):
        if self.app.busy: return
        from x_support import post_url, post_urls, profile_url
        source = self.source.get()
        source = {'主页图片': '主页作品', '评论图片': '评论作品'}.get(source, source)
        if resume and not source.startswith('主页'):
            messagebox.showinfo('继续采集', '继续采集用于主页作品，请切换到主页作品。')
            return
        try:
            if source == '作品链接':
                urls = post_urls(self.url.get())
            else:
                url, _ = (profile_url if source.startswith('主页') else post_url)(self.url.get())
        except ValueError as error:
            messagebox.showinfo('检查链接', str(error)); return
        mode = self.mode.get()
        if resume and self.result_mode != mode:
            messagebox.showinfo('继续采集', '采集类型已改变，请点击获取作品重新采集。')
            return
        if not resume:
            self.items = []; self._render()
        self.result_source = source
        self.result_mode = mode
        messages = {
            '作品链接': '正在解析 X 作品链接，完成后可勾选保存…',
            '主页作品': '正在从主页帖子逐条采集作品，本轮最多 90 秒，可分批继续…',
            '评论作品': '正在获取评论作品，完成后可自行勾选下载…',
        }
        self.summary.set('正在继续采集，保留已有结果并自动去重…' if resume else messages[source])
        def job():
            last = ()
            def publish(found):
                nonlocal last
                checked = len(getattr(service.browser, 'profile_posts', ())) if source.startswith('主页') else 0
                detail = f'已检查 {checked} 条主页帖子，' if source.startswith('主页') else ''
                if source != '作品链接':
                    self.app.emit_progress(0, f'正在获取 X {source}，{detail}已找到 {len(found)} 项{mode}')
                signature = tuple(item.identifier for item in found)
                if signature != last:
                    last = signature
                    self.app.events.put(('x_batch', list(found)))
            try:
                service = self.get_service()
                failures = 0
                if source == '作品链接':
                    items, failures = service.posts(urls, self.app.cancel, publish, mode)
                else:
                    fetch = service.profile_next if resume else (service.profile if source == '主页作品' else service.search)
                    items = fetch(url, self.app.cancel, publish, mode)
            except Exception as error:
                self.app.events.put(('x_error', str(error)))
                raise
            self.app.events.put(('x_batch', items))
            pending_thumbnails = [item for item in items if not item.thumbnail_bytes]
            self.get_service().thumbnails(pending_thumbnails, lambda key, data: self.app.events.put(('x_thumbnail', (key, data))))
            result = f'获取完成：找到 {len(items)} 项 X {source}（{mode}），请自行勾选下载。'
            return result + (f' {failures} 条链接解析失败，详见任务日志。' if failures else '')
        self.app.run_job(job)

    def handle_batch(self, items):
        selected = {key for key, value in self.selected.items() if value.get()}
        thumbnails = {item.identifier: item.thumbnail_bytes for item in self.items if item.thumbnail_bytes}
        self.items = items
        for item in self.items:
            if not item.thumbnail_bytes:
                item.thumbnail_bytes = thumbnails.get(item.identifier, b'')
        browser = self.service.browser if self.service else None
        reason = getattr(browser, 'profile_stop_reason', '') if self.result_source.startswith('主页') else ''
        self.summary.set(f'{self.result_source}：累计找到 {len(items)} 项，请勾选后下载。' + (reason + '。' if reason else ''))
        self._render()
        for key in selected:
            if key in self.selected:
                self.selected[key].set(True)
        self._selection()

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
            saved, failed, skipped = self.get_service().download(items, folder, self.result_mode, self.app.mute.get(), self.app.cancel)
            self.app.events.put(('x_saved', (saved, failed, skipped)))
            return f'X 作品保存完成：成功 {len(saved)} 项，失败 {len(failed)} 项，重复跳过 {skipped} 项。'
        self.app.run_job(job)

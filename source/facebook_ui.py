"""A manual-start Facebook profile archive panel."""
import tkinter as tk
from pathlib import Path
import customtkinter as ctk
from ui import components, MUTED, INK, BG, CARD, ACCENT
from mac_theme import T


class FacebookPanel(ctk.CTkFrame):
    def __init__(self, parent, app, data_dir, saved):
        super().__init__(parent, fg_color='transparent')
        self.app, self.data_dir, self.service = app, Path(data_dir), None
        font,label,button=components()
        self.url=tk.StringVar(value=saved.get('facebook_profile_url','https://www.facebook.com/share/1SLivrDLeB/?mibextid=wwXIfr'))
        self.destination=tk.StringVar(value=saved.get('facebook_folder',r'C:\工作\素材'))
        self.grid_columnconfigure(0,weight=1)
        self.grid_rowconfigure(8,weight=1)
        label(self,'保存来源',font=font(16,'bold')).grid(row=0,column=0,sticky='w',pady=(0,8))
        source=ctk.CTkFrame(self,fg_color=CARD,corner_radius=9,border_width=1,border_color=T['rule'])
        source.grid(row=1,column=0,sticky='ew')
        source.grid_columnconfigure(1,weight=1)
        for rowindex,title in [(0,'博主主页'),(2,'保存位置'),(4,'登录状态')]:
            label(source,title,font=font(15),width=115,anchor='w').grid(row=rowindex,column=0,sticky='w',padx=16,pady=10)
        for rowindex in (1,3):
            ctk.CTkFrame(source,height=1,fg_color=T['rule']).grid(row=rowindex,column=0,columnspan=3,sticky='ew')
        self.entry=ctk.CTkEntry(source,textvariable=self.url,height=34,font=font(15))
        self.entry.grid(row=0,column=1,columnspan=2,sticky='ew',padx=(0,16),pady=8)
        self.folder_entry=ctk.CTkEntry(source,textvariable=self.destination,height=34,font=font(15))
        self.folder_entry.grid(row=2,column=1,sticky='ew',pady=8)
        self.choose=button(source,'更改',self.choose_folder,width=64)
        self.choose.grid(row=2,column=2,padx=(10,16),pady=8)
        label(source,'使用内置浏览器',font=font(15),text_color=MUTED,anchor='w').grid(row=4,column=1,sticky='w')
        self.login=button(source,'登录',self.open_browser,width=64)
        self.login.grid(row=4,column=2,padx=(10,16),pady=8)
        label(self,'素材类型',font=font(16,'bold')).grid(row=2,column=0,sticky='w',pady=(16,8))
        types=ctk.CTkFrame(self,fg_color=CARD,corner_radius=9,border_width=1,border_color=T['rule']);types.grid(row=3,column=0,sticky='ew')
        types.grid_columnconfigure((0,2),weight=1,uniform='media')
        ctk.CTkFrame(types,width=1,height=1,fg_color=T['rule']).grid(row=0,column=1,rowspan=3,sticky='ns',pady=10)
        ctk.CTkFrame(types,height=1,fg_color=T['rule']).grid(row=1,column=0,columnspan=3,sticky='ew',padx=10)
        saved_types=saved.get('facebook_types',{})
        if not isinstance(saved_types,dict):saved_types={}
        self.types={};self.type_switches=[]
        for key,title,rowindex,column in [('photos','照片',0,0),('albums','相册',2,0),('videos','视频',0,2),('reels','Reels',2,2)]:
            cell=ctk.CTkFrame(types,fg_color='transparent');cell.grid(row=rowindex,column=column,sticky='ew',padx=16,pady=10)
            label(cell,title,font=font(15)).pack(side='left')
            value=tk.BooleanVar(value=bool(saved_types.get(key,True)));self.types[key]=value
            switch=ctk.CTkSwitch(cell,text='',variable=value,width=42,switch_width=38,switch_height=22,progress_color=ACCENT,button_color=CARD,button_hover_color=CARD)
            switch.pack(side='right');self.type_switches.append(switch)
        label(self,'扫描数量',font=font(16,'bold')).grid(row=4,column=0,sticky='w',pady=(16,8))
        limits=ctk.CTkFrame(self,fg_color=CARD,corner_radius=9,border_width=1,border_color=T['rule']);limits.grid(row=5,column=0,sticky='ew')
        label(limits,'扫描并下载',font=font(15)).pack(side='left',padx=16,pady=12)
        label(limits,'项',font=font(15)).pack(side='right',padx=(8,16))
        self.item_limit=tk.StringVar(value=str(saved.get('facebook_item_limit',200)))
        entry=ctk.CTkEntry(limits,textvariable=self.item_limit,width=90,height=34,font=font(14))
        entry.pack(side='right');self.limit_entries=[entry]
        label(self,'照片和视频合计；重复跳过，实际保存可能少于设定数量。',font=font(13),text_color=MUTED).grid(row=6,column=0,sticky='w',padx=12,pady=(6,0))
        label(self,'仅获取当前账号可访问的公开作品。作者标识保留；不会用截图替代原图。\n加载中断或访问受限时会明确提示，扫描停止不代表已获取全部历史作品。',font=font(13),text_color=MUTED,justify='left',wraplength=800).grid(row=7,column=0,sticky='w',padx=12,pady=(6,0))
        self.start=button(self,'开始扫描并保存',self.download,primary=True,width=185)
        self.start.grid(row=9,column=0,sticky='e',pady=(8,0))
        self.controls=[self.entry,self.folder_entry,self.choose,self.start,self.login,*self.type_switches,*self.limit_entries]

    def get_service(self):
        if self.service is None:
            from facebook_profile import FacebookArchive
            self.service=FacebookArchive(self.data_dir,self.app.emit_log,self.app.emit_progress)
        return self.service

    def open_browser(self):
        if not self.app.busy:self.app.run_job(lambda:self.get_service().open_login())

    def settings(self):
        return {'facebook_profile_url':self.url.get().strip(),'facebook_folder':self.destination.get().strip(),
                'facebook_types':{key:value.get() for key,value in self.types.items()},
                'facebook_item_limit':self.item_limit.get().strip()}

    def choose_folder(self):
        from tkinter import filedialog
        folder=filedialog.askdirectory(title='选择 Facebook 素材保存位置')
        if folder:self.destination.set(folder)

    def set_busy(self,value):
        for control in self.controls:control.configure(state='disabled' if value else 'normal')

    def download(self):
        if self.app.busy:return
        url,folder=self.url.get().strip(),self.destination.get().strip()
        if not folder:
            self.app.status.set('请先填写 Facebook 素材保存位置。');return
        categories=[key for key,value in self.types.items() if value.get()]
        if not categories:
            self.app.status.set('请至少开启一种类型：照片、相册、视频或 Reels。');return
        from facebook_limits import parse_item_limit
        try:limit=parse_item_limit(self.item_limit.get())
        except ValueError as error:self.app.status.set(str(error));return
        def job():
            return self.get_service().run(url,Path(folder),self.app.cancel,categories=categories,
                                          item_limit=limit)
        self.app.run_job(job)

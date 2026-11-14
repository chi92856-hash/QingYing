from pathlib import Path
from io import BytesIO
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from PIL import Image,ImageOps

class CollectorPanel(ctk.CTkFrame):
    def __init__(self,parent,app,data_dir,saved=None):
        super().__init__(parent,fg_color='transparent')
        self.app=app;self.items=[];self.seen=set();self.active_signature=None
        self.service=None;self.data_dir=Path(data_dir);self.selected={};self.cards={};self.thumbnails={}
        saved=saved or {}
        self.keyword=tk.StringVar(value=saved.get('collector_keyword',''))
        self.topic=tk.StringVar(value=saved.get('collector_topic',''))
        self.mode=tk.StringVar(value=saved.get('collector_mode','图片'))
        self.sort=tk.StringVar(value=saved.get('collector_sort','综合'))
        self.summary=tk.StringVar(value='按关键词返回网页前 5 个结果，勾选后下载。')
        self.grid_columnconfigure(0,weight=1);self.grid_rowconfigure(3,weight=1)
        font=lambda n=12,w='normal':ctk.CTkFont(family='Microsoft YaHei UI',size=max(12,n),weight=w)
        def btn(parent,text,command,width=110,primary=False):
            return ctk.CTkButton(parent,text=text,command=command,width=width,height=34,corner_radius=8,font=font(),
                fg_color='#007AFF' if primary else '#F2F3F6',hover_color='#006BE0' if primary else '#E5E8ED',text_color='white' if primary else '#007AFF')
        top=ctk.CTkFrame(self,fg_color='transparent');top.grid(row=0,column=0,sticky='ew',padx=18,pady=(15,7))
        top.grid_columnconfigure(1,weight=3);top.grid_columnconfigure(3,weight=2)
        ctk.CTkLabel(top,text='关键词',font=font(),text_color='#202126').grid(row=0,column=0,padx=(0,8))
        self.key_entry=ctk.CTkEntry(top,textvariable=self.keyword,placeholder_text='例如：风景摄影',font=font(),height=34)
        self.key_entry.grid(row=0,column=1,sticky='ew')
        ctk.CTkLabel(top,text='话题',font=font(),text_color='#202126').grid(row=0,column=2,padx=(12,8))
        self.topic_entry=ctk.CTkEntry(top,textvariable=self.topic,placeholder_text='可选；作为附加搜索词',font=font(),height=34)
        self.topic_entry.grid(row=0,column=3,sticky='ew')
        self.key_entry.bind('<Return>',lambda e:self.search(False))
        options=ctk.CTkFrame(self,fg_color='transparent');options.grid(row=1,column=0,sticky='ew',padx=18,pady=(0,7))
        ctk.CTkLabel(options,text='素材',font=font(),text_color='#737780').pack(side='left')
        self.mode_box=ctk.CTkOptionMenu(options,values=['图片','视频','全部'],variable=self.mode,width=90,height=32,font=font(),fg_color='#F1F3FA',button_color='#E3E7F6',text_color='#202126')
        self.mode_box.pack(side='left',padx=(7,12))
        self.sort_box=ctk.CTkOptionMenu(options,values=['综合','最新','最多点赞'],variable=self.sort,width=112,height=32,font=font(),fg_color='#F1F3FA',button_color='#E3E7F6',text_color='#202126')
        self.sort_box.pack(side='left')
        self.next_btn=btn(options,'换一批',lambda:self.search(True),width=88)
        self.next_btn.pack(side='right')
        self.search_btn=btn(options,'搜索 5 个',lambda:self.search(False),width=108,primary=True)
        self.search_btn.pack(side='right',padx=(8,7))
        self.login_btn=btn(options,'打开小红书 / 登录',self.login,width=150)
        self.login_btn.pack(side='right',padx=(8,0))
        self.info=ctk.CTkLabel(self,textvariable=self.summary,anchor='w',justify='left',font=font(11),text_color='#737780',wraplength=810)
        self.info.grid(row=2,column=0,sticky='ew',padx=18,pady=(0,4))
        self.listbox=ctk.CTkScrollableFrame(self,fg_color='#F5F7FB',corner_radius=10)
        self.listbox.grid(row=3,column=0,sticky='nsew',padx=18,pady=(0,7));self.listbox.grid_columnconfigure(0,weight=1)
        bottom=ctk.CTkFrame(self,fg_color='transparent');bottom.grid(row=4,column=0,sticky='ew',padx=18,pady=(0,12))
        self.all_var=tk.BooleanVar(value=False)
        self.all_check=ctk.CTkCheckBox(bottom,text='全选本批',variable=self.all_var,command=self.select_all,font=font(),width=95)
        self.all_check.pack(side='left')
        self.mute_switch=ctk.CTkSwitch(bottom,variable=app.mute,text='静音',width=80,font=font(10),progress_color='#007AFF')
        self.mute_switch.pack(side='left',padx=(4,0))
        ctk.CTkLabel(bottom,text='原图优先 · 实况仅存照片 · 自动去重',font=font(10),text_color='#737780').pack(side='left',padx=10)
        self.save_btn=btn(bottom,'下载所选（0）',self.download,width=150,primary=True);self.save_btn.pack(side='right')
        self.controls=[self.key_entry,self.topic_entry,self.mode_box,self.sort_box,self.search_btn,self.next_btn,self.login_btn,self.all_check,self.mute_switch]
        self._render()
    def get_service(self):
        if self.service is None:
            from collector import get_collector
            self.service=get_collector(self.app)
        return self.service
    def settings(self):
        return {'collector_keyword':self.keyword.get(),'collector_topic':self.topic.get(),'collector_mode':self.mode.get(),'collector_sort':self.sort.get()}
    def set_busy(self,value):
        for widget in self.controls:widget.configure(state='disabled' if value else 'normal')
        for identifier,checkbox in self.cards.items():
            done=self.service is not None and self.service.history.contains(identifier)
            checkbox.configure(state='disabled' if value or done else 'normal')
        self._selection()
    def _selection(self):
        count=sum(v.get() for v in self.selected.values())
        self.save_btn.configure(text=f'下载所选（{count}）',state='disabled' if self.app.busy or not count else 'normal')
        self.next_btn.configure(state='normal' if self.items and not self.app.busy else 'disabled')
    def select_all(self):
        for identifier,var in self.selected.items():
            done=self.service is not None and self.service.history.contains(identifier)
            var.set(self.all_var.get() and not done)
        self._selection()
    def _render(self):
        for child in self.listbox.winfo_children():child.destroy()
        self.selected={};self.cards={};self.thumbnails={};self.all_var.set(False)
        if not self.items:
            ctk.CTkLabel(self.listbox,text='候选作品会显示在这里\n先预览、再勾选下载；未勾选的作品不记入采集历史。',text_color='#8792A8',font=('Microsoft YaHei UI',12),height=130).grid(row=0,column=0,sticky='ew')
        for index,item in enumerate(self.items):
            card=ctk.CTkFrame(self.listbox,fg_color='white',corner_radius=12,border_width=1,border_color='#E8ECF4')
            card.grid(row=index,column=0,sticky='ew',pady=4,padx=2);card.grid_columnconfigure(2,weight=1)
            done=self.service is not None and self.service.history.contains(item.identifier)
            var=tk.BooleanVar(value=False);self.selected[item.identifier]=var
            checkbox=ctk.CTkCheckBox(card,text='',variable=var,command=self._selection,width=25,state='disabled' if done or self.app.busy else 'normal')
            checkbox.grid(row=0,column=0,rowspan=2,padx=(10,3),pady=12);self.cards[item.identifier]=checkbox
            image=self._thumbnail_image(item.thumbnail_bytes)
            thumb=ctk.CTkLabel(card,text='' if image else item.kind,image=image,width=76,height=76,fg_color='#E9EDF5',corner_radius=6,text_color='#737780')
            thumb.grid(row=0,column=1,rowspan=2,padx=(3,10),pady=9)
            self.thumbnails[item.identifier]=thumb
            ctk.CTkLabel(card,text=item.title[:100],anchor='w',justify='left',wraplength=470,font=('Microsoft YaHei UI',12,'bold'),text_color='#202126').grid(row=0,column=2,sticky='ew',pady=(9,0))
            caption=('已采集，下次自动跳过' if done else item.kind)+'  ·  '+(item.author[:28] or '作者未显示')+('  ·  赞 '+item.likes if item.likes else '')
            ctk.CTkLabel(card,text=caption,anchor='w',font=('Microsoft YaHei UI',10),text_color='#737780').grid(row=1,column=2,sticky='ew',pady=(0,9))
            ctk.CTkButton(card,text='看作品',width=70,height=28,fg_color='#F2F3F6',hover_color='#E5E8ED',text_color='#007AFF',command=lambda u=item.url:self.open_note(u)).grid(row=0,column=3,rowspan=2,padx=10)
        self._selection()
    def _thumbnail_image(self,data):
        if not data:return None
        try:
            with Image.open(BytesIO(data)) as im:
                canvas=Image.new('RGB',(76,76),'#E9EDF5')
                small=ImageOps.contain(im.convert('RGB'),(76,76))
                canvas.paste(small,((76-small.width)//2,(76-small.height)//2))
                return ctk.CTkImage(canvas,size=(76,76))
        except Exception:return None
    def handle_thumbnail(self,payload):
        identifier,data=payload
        item=next((item for item in self.items if item.identifier==identifier),None)
        widget=self.thumbnails.get(identifier)
        if item is None or widget is None:return
        image=self._thumbnail_image(data)
        if image is not None:
            item.thumbnail_bytes=data
            widget.configure(image=image,text='')
    def search(self,next_batch=False):
        if self.app.busy:return
        keyword,topic,mode,sort=self.keyword.get().strip(),self.topic.get().strip(),self.mode.get(),self.sort.get()
        if not keyword and not topic:
            messagebox.showinfo('填写搜索条件','请输入关键词或话题。');return
        signature=(keyword,topic,mode,sort)
        if not next_batch or signature!=self.active_signature:self.seen=set()
        self.active_signature=signature
        excluded=set(self.seen)
        self.items=[];self._render()
        self.summary.set('正在按关键词读取搜索结果，最多返回 5 个。')
        def publish(items,counts):
            self.app.events.put(('collector_batch',(items,counts,mode)))
            message=f'已读取 {counts.get("read",0)} 条 · 搜索结果 {len(items)}/5'
            self.app.emit_progress(min(95,len(items)*20) if counts.get('searching') else 100,message)
        def job():
            items,counts=self.get_service().search(keyword,topic,mode,sort,excluded,self.app.cancel,on_update=publish)
            self.get_service().load_thumbnails(items,lambda identifier,data:self.app.events.put(('collector_thumbnail',(identifier,data))))
            reason=counts.get('reason','')
            return f'已显示 {len(items)}/5 个搜索结果。'+(reason or '请勾选后下载。')
        self.app.run_job(job)
    def handle_batch(self,payload):
        previous=tuple(c.identifier for c in self.items)
        self.items,counts,self.batch_mode=payload
        self.seen.update(c.identifier for c in self.items)
        phase='正在搜索' if counts.get('searching') else '搜索完成'
        self.summary.set(f'{phase}：{len(self.items)}/5 个网页结果。'+counts.get('reason',''))
        if previous!=tuple(c.identifier for c in self.items) or not counts.get('searching'):
            self._render()
    def login(self):
        if self.app.busy:return
        self.app.run_job(lambda:self.get_service().login())
    def open_note(self,url):
        if self.app.busy:return
        self.app.run_job(lambda:self.get_service().open_note(url))
    def download(self):
        if self.app.busy:return
        candidates=[item for item in self.items if self.selected[item.identifier].get()]
        if not candidates:return
        try:folder=self.app.output_dir()
        except Exception as e:messagebox.showerror('保存位置',str(e));return
        mode=getattr(self,'batch_mode',self.mode.get());mute=self.app.mute.get()
        def job():
            saved,failed,skipped=self.get_service().download(candidates,folder,mode,mute,self.app.cancel)
            self.app.events.put(('collector_saved',(saved,failed,skipped)))
            total=sum(len(files) for _,files in saved)
            return f'采集结束：完整保存 {len(saved)} 篇 / {total} 个文件，重复跳过 {skipped}，失败 {len(failed)}。'
        self.app.run_job(job)
    def handle_saved(self,payload):
        saved,failed,skipped=payload
        self.summary.set(f'本次完整保存 {len(saved)} 篇，失败 {len(failed)} 篇；失败不记入去重。历史共 {self.service.history.count()} 篇。')
        self._render()
    def close(self):
        if self.service:
            self.service.close()

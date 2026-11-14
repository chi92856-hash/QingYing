from __future__ import annotations
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk
from ui import build_ui, build_editor
from PIL import Image, ImageTk
from common import Cancelled, IMAGE_EXTS, load_settings, save_settings

APP_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
CONFIG = APP_DIR / 'settings.json'
PENDING = APP_DIR / 'pending_downloads.json'

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        from updater import VERSION
        self.title(f'清影 v{VERSION} · 素材工作台')
        self.update_offer = None
        self.geometry('1240x900')
        self.minsize(1180, 860)
        self.configure(fg_color='#F7F8FA')
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.source = None
        self.original = None
        self.boxes = []
        self.duration = None
        self.show_result = False
        self.closing = False
        self.collector_panel=None
        self.instagram_service=None
        self.facebook_panel=None
        try:pending=json.loads(PENDING.read_text('utf-8'))
        except (OSError,ValueError):pending={}
        if not isinstance(pending,dict):pending={}
        values=pending.get('urls',[])
        self.pending_urls=[u for u in values if isinstance(u,str) and u.startswith('https://')][:1000] if isinstance(values,list) else []
        try:self.instagram_retry_at=float(pending.get('retry_at') or 0)
        except (ValueError,TypeError):self.instagram_retry_at=0
        self.notice=tk.StringVar(value=f'有 {len(self.pending_urls)} 条待下载，可点击继续。' if self.pending_urls else '支持多条链接 · 实况图仅保存照片')
        self._progress_lock=threading.Lock();self._latest_progress=None
        self._draw_job=None;self._read_generation=0;self._frame_running=False
        saved = load_settings(CONFIG)
        folder = saved.get('folder')
        if not isinstance(folder, str) or not folder.strip():
            folder = str(APP_DIR / '已保存作品')
        self.folder = tk.StringVar(value=folder)
        self.cookie = tk.StringVar()
        self.mute = tk.BooleanVar(value=saved.get('mute') is True)
        self.status = tk.StringVar(value='准备就绪')
        self.video_pos = tk.DoubleVar(value=0)
        self.style_ui()
        self.saved_settings=saved
        self.data_dir=APP_DIR/'collector_data'
        self.build()
        self.after(100, self.poll)
        self.protocol('WM_DELETE_WINDOW', self.close)

    def style_ui(self):
        from mac_theme import install_theme
        install_theme()

    def build(self):
        build_ui(self)

    def show_page(self, name):
        if name=='x' and getattr(self,'x_panel',None) is None:
            from x_ui import XPanel
            self.x_panel=XPanel(self.pages['x'],self,APP_DIR/'x_data')
            self.x_panel.pack(fill='both',expand=True)
            self.x_panel.set_busy(self.busy)
        if name=='facebook' and self.facebook_panel is None:
            from facebook_ui import FacebookPanel
            self.facebook_panel=FacebookPanel(self.pages['facebook'],self,APP_DIR/'facebook_data',self.saved_settings)
            self.facebook_panel.pack(fill='both',expand=True)
            self.facebook_panel.set_busy(self.busy)
        if name=='edit' and not hasattr(self,'canvas'):build_editor(self)
        if name=='collector' and self.collector_panel is None:
            from collector_ui import CollectorPanel
            self.collector_panel=CollectorPanel(self.pages['collector'],self,self.data_dir,self.saved_settings)
            self.collector_panel.pack(fill='both',expand=True)
            self.collector_panel.set_busy(self.busy)
        self.pages[name].tkraise()
        if name=='facebook':self.output_panel.grid_remove()
        else:self.output_panel.grid()
        if hasattr(self,'stop_btn'):self.stop_btn.configure(text='暂停' if name=='facebook' else '取消')
        self.page_title.configure(text={'download':'链接下载','edit':'水印修复','collector':'小红书采集','facebook':'Facebook 主页','x':'X 图片获取'}[name])
        self.page_subtitle.configure(text={'download':'把喜欢的作品，清晰地留在本地。','edit':'框选水印区域，让画面回归干净。','collector':'按关键词发现素材，挑选后再保存。','facebook':'按需保存公开图片与视频。','x':'获取主页与评论图片，预览并勾选后保存原图。'}[name])
        for key, button in [('download', self.nav_download), ('edit', self.nav_edit), ('collector',self.nav_collector),('facebook',self.nav_facebook),('x',self.nav_x)]:
            from mac_theme import icon
            button.configure(image=icon(key,'#007AFF' if key==name else '#737780',19),fg_color='#D9E9FF' if key == name else 'transparent',
                             text_color='#007AFF' if key == name else '#68758A')

    def add_log(self, message):
        self.logbox.configure(state='normal')
        self.logbox.insert('end', str(message)+'\n')
        lines=int(self.logbox.index('end-1c').split('.')[0])
        if lines>400:self.logbox.delete('1.0',f'{lines-350}.0')
        self.logbox.see('end')
        self.logbox.configure(state='disabled')

    def emit_log(self, text):
        self.events.put(('log', str(text)))

    def emit_progress(self, value, text):
        with self._progress_lock:self._latest_progress=(value,text)

    def poll(self):
        with self._progress_lock:
            progress,self._latest_progress=self._latest_progress,None
        if progress:self.progress.set(progress[0]/100);self.status.set(progress[1])
        logs=[];started=time.monotonic()
        for _ in range(80):
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                logs.append(str(payload))
            elif kind == 'media_loaded':
                generation,path,original,duration=payload
                if generation==self._read_generation:
                    self.source=path;self.original=original;self.duration=duration
                    self.boxes=[];self.show_result=False;self.video_pos.set(0)
                    self.file_label.configure(text=path.name[:38])
                    self.slider.configure(state='disabled' if duration is None else 'normal')
                    self.draw()
            elif kind == 'frame_loaded':
                generation,image,position,error=payload;self._frame_running=False
                if generation==self._read_generation:
                    if error:self.status.set(error)
                    elif abs(self.video_pos.get()-position)<.1:self.original=image;self.draw()
                    else:self.load_frame()
            elif kind == 'preview_ready':
                self.result_image=payload;self.show_result=True;self.draw()
            elif kind == 'download_state':
                self.pending_urls,self.instagram_retry_at,message=payload
                self.notice.set(message)
                try:
                    temporary=PENDING.with_suffix('.tmp')
                    temporary.write_text(json.dumps({'urls':self.pending_urls,'retry_at':self.instagram_retry_at},ensure_ascii=False),encoding='utf-8')
                    temporary.replace(PENDING)
                except OSError:self.add_log('待下载列表未能写入文件，请先复制输入框链接留存。')
            elif kind == 'collector_batch':
                self.collector_panel.handle_batch(payload)
            elif kind == 'collector_thumbnail':
                self.collector_panel.handle_thumbnail(payload)
            elif kind == 'x_batch':
                self.x_panel.handle_batch(payload)
            elif kind == 'x_thumbnail':
                self.x_panel.handle_thumbnail(payload)
            elif kind == 'x_saved':
                self.x_panel.handle_saved(payload)
            elif kind == 'x_error':
                self.x_panel.handle_error(payload)
            elif kind == 'update_offer':
                self.update_offer = payload
            elif kind == 'update_ready' and not self.closing:
                try:
                    os.startfile(str(payload))
                except OSError:
                    logs.append(f'更新文件位置：{payload}')
            elif kind == 'collector_saved':
                self.collector_panel.handle_saved(payload)
            elif kind == 'progress':
                value, text = payload
                self.progress.set(value / 100)
                self.status.set(text)
            elif kind == 'done':
                with self._progress_lock:self._latest_progress=None
                self.set_busy(False)
                self.status.set(payload.splitlines()[0][:90])
                if not payload.startswith(('失败：','已取消','任务已取消','已暂停')):self.progress.set(1)
                logs.append(payload)
                if self.closing:
                    self.shutdown()
                    return
                if self.update_offer is not None:
                    from updater import offer_download
                    offer, self.update_offer = self.update_offer, None
                    self.after_idle(lambda offer=offer:offer_download(self, offer))
            if time.monotonic()-started>.012:break
        if logs:self.add_log('\n'.join(logs))
        self.after(100, self.poll)

    def set_busy(self, value):
        self.busy = value
        for widget in self.lock_controls:
            widget.configure(state='disabled' if value else 'normal')
        self.links.configure(state='disabled' if value else 'normal')
        self.stop_btn.configure(state='normal' if value else 'disabled')
        if hasattr(self,'slider'):self.slider.configure(state='disabled' if value or self.duration is None else 'normal')
        if self.collector_panel:self.collector_panel.set_busy(value)
        if self.facebook_panel:self.facebook_panel.set_busy(value)
        if getattr(self,'x_panel',None):self.x_panel.set_busy(value)
        self.resume_btn.configure(state='normal' if self.pending_urls and not value else 'disabled')
        self.activity.configure(text='处理中' if value else '就绪',text_color='#007AFF' if value else '#17846F')

    def run_job(self, function):
        self.cancel.clear()
        self.set_busy(True)
        self.progress.set(0)
        with self._progress_lock:self._latest_progress=None
        self.status.set('正在处理…')
        try:
            options=self.collector_panel.settings() if self.collector_panel else {}
            if self.facebook_panel:options.update(self.facebook_panel.settings())
            self.saved_settings.update({'folder':self.folder.get(),'mute':self.mute.get(),**options})
            save_settings(CONFIG, self.saved_settings)
        except OSError:
            self.add_log('设置未能保存，请检查程序目录是否可写。')
        def work():
            try:
                message = function()
            except Cancelled as error:
                message = str(error)
            except Exception as error:
                message = '失败：' + str(error)
            self.events.put(('done', message))
        threading.Thread(target=work, daemon=True).start()

    def output_dir(self):
        text = self.folder.get().strip()
        if not text:
            raise ValueError('请先选择保存文件夹。')
        folder = Path(text).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def select_folder(self):
        path = filedialog.askdirectory(title='选择保存位置')
        if path:
            self.folder.set(path)

    def open_folder(self):
        try:
            os.startfile(str(self.output_dir()))
        except Exception as error:
            messagebox.showerror('无法打开文件夹', str(error))

    def select_cookie(self):
        path = filedialog.askopenfilename(title='选择 Netscape 格式的 Cookies.txt',filetypes=[('Cookies 文本','*.txt'),('全部文件','*.*')])
        if path:
            self.cookie.set(path)

    def paste(self):
        try:
            text = self.clipboard_get()
            if self.links.get('1.0','end').strip():
                self.links.insert('end','\n')
            self.links.insert('end',text)
        except tk.TclError:
            self.status.set('剪贴板没有文本')

    def start_download(self):
        try:
            text = self.links.get('1.0','end')
            folder = self.output_dir()
            cookie = self.cookie.get()
            mute = self.mute.get()
            existing_pending=list(self.pending_urls)
            retry_at=self.instagram_retry_at
        except Exception as error:
            messagebox.showerror('检查输入', str(error))
            return
        def job():
            from core import Downloader,share_urls,social_platform
            from instagram_support import download_batch,InstagramRateLimited,InstagramAccessError
            urls=share_urls(text)
            blocked=None;cookies=[]
            if any(social_platform(url)=='Instagram' for url in urls):
                if retry_at>time.time():
                    blocked=InstagramRateLimited(retry_at)
                elif not cookie:
                    try:cookies=self.get_instagram_service().call('cookies')
                    except InstagramAccessError as error:blocked=error
                    if not blocked and not cookies:blocked=InstagramAccessError('请先点击“Instagram 登录”，在清影内置浏览器完成登录或验证后继续。')
            downloader = Downloader(self.cancel,self.emit_log,self.emit_progress,cookie,mute=mute,instagram_cookies=cookies)
            def resolve_xhs(url):
                from collector import get_collector
                return get_collector(self).browser.call('resolve', url, self.cancel)
            downloader.resolve_xhs = resolve_xhs
            if any(social_platform(url)=='X' for url in urls):
                if getattr(self,'x_service',None) is None:
                    from x_support import XService
                    self.x_service=XService(APP_DIR/'x_data',self.emit_log,self.emit_progress)
                downloader.x_browser=self.x_service.browser
            try:
                result=download_batch(downloader,urls,folder,existing_pending,blocked)
            finally:
                downloader.session.close()
            deadline=getattr(result.blocked,'retry_at',0) if result.blocked else 0
            if result.cancelled:
                message=f'任务已取消；{len(result.pending)} 条待下载链接已保留。'
                self.events.put(('download_state',(result.pending,deadline,message)))
                return f'已取消：本批已保存 {result.files} 个文件；{len(result.pending)} 条链接可继续下载。'
            if result.blocked:
                left=max(0,int(deadline-time.time()))
                wait=f'建议等待约 {max(1,(left+59)//60)} 分钟后重试。' if left else '请先完成登录或验证。'
                message=f'Instagram 已暂停；{len(result.pending)} 条已保留。{wait}'
                self.events.put(('download_state',(result.pending,deadline,message)))
                self.emit_log(str(result.blocked))
                return '已暂停 Instagram：'+wait+f' 待下载 {len(result.pending)} 条；本批已保存 {result.files} 个文件。'
            self.events.put(('download_state',(result.pending,0,f'有 {len(result.pending)} 条待下载。' if result.pending else '支持多条链接 · 实况图仅保存照片')))
            if result.failed:
                return f'批量任务结束：已保存 {result.files} 个文件；{result.failed} 条链接失败或部分失败，详见日志。'
            self.emit_progress(100,'下载完成')
            return f'完成，已保存 {result.files} 个文件。点击“打开文件夹”查看。'
        self.run_job(job)

    def get_instagram_service(self):
        if self.instagram_service is None:
            from instagram_support import create_browser
            self.instagram_service=create_browser(APP_DIR/'instagram_data',self.emit_log)
        return self.instagram_service

    def instagram_login(self):
        if self.busy:return
        self.run_job(lambda:self.get_instagram_service().call('login'))

    def resume_download(self):
        if self.busy or not self.pending_urls:return
        if self.instagram_retry_at>time.time():
            seconds=int(self.instagram_retry_at-time.time())
            self.status.set(f'Instagram 请求仍在暂停，约 {max(1,(seconds+59)//60)} 分钟后可重试；未发送新请求。')
            return
        self.links.delete('1.0','end');self.links.insert('1.0','\n'.join(self.pending_urls))
        self.start_download()

    def select_media(self):
        path = filedialog.askopenfilename(title='选择图片或视频',filetypes=[('图片和视频','*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.mp4 *.mov *.mkv *.avi *.webm *.m4v'),('全部文件','*.*')])
        if not path:
            return
        self._read_generation+=1;generation=self._read_generation
        def job():
            from core import load_preview
            original,duration=load_preview(path)
            self.events.put(('media_loaded',(generation,Path(path),original,duration)))
            return '文件已就绪，拖动框选水印区域。'
        self.run_job(job)

    def seek(self, value):
        if self.busy or self.duration is None or not self.source:
            return
        if getattr(self,'_seek_job',None):
            self.after_cancel(self._seek_job)
        self._seek_job = self.after(200,self.load_frame)

    def load_frame(self):
        self._seek_job = None
        if self._frame_running or self.busy or not self.source:return
        self._frame_running=True;generation=self._read_generation
        path,position=self.source,self.video_pos.get()
        def read():
            from core import load_preview
            try:image,_=load_preview(path,position/100);error=None
            except Exception as e:image=None;error=str(e)
            self.events.put(('frame_loaded',(generation,image,position,error)))
        threading.Thread(target=read,daemon=True).start()

    def schedule_draw(self):
        if self._draw_job:self.after_cancel(self._draw_job)
        self._draw_job=self.after(60,self.draw)

    def draw(self):
        self._draw_job=None
        if not hasattr(self,'canvas'):return
        self.canvas.delete('all')
        cw,ch = self.canvas.winfo_width(),self.canvas.winfo_height()
        if self.original is None:
            self.canvas.create_text(cw/2,ch/2,text='选择本地文件后，在这里框选水印',fill='#aabbce',font=('Microsoft YaHei UI',14))
            return
        image = getattr(self,'result_image',self.original) if self.show_result else self.original
        w,h = image.size
        self.scale = min(max(1,cw-20)/w,max(1,ch-20)/h)
        sw,sh = max(1,int(w*self.scale)),max(1,int(h*self.scale))
        self.offset = ((cw-sw)//2,(ch-sh)//2)
        cache=(id(image),sw,sh)
        if cache!=getattr(self,'_image_cache_key',None):
            self.tkimage=ImageTk.PhotoImage(image.resize((sw,sh),Image.Resampling.BILINEAR))
            self._image_cache_key=cache
        self.canvas.create_image(*self.offset,anchor='nw',image=self.tkimage)
        if not self.show_result:
            for i,box in enumerate(self.boxes,1):
                a,b,c,d = self.to_canvas(box)
                self.canvas.create_rectangle(a,b,c,d,outline='#61dfff',width=2)
                self.canvas.create_text(a+4,b+4,text=str(i),anchor='nw',fill='#61dfff')

    def to_canvas(self,box):
        ox,oy = self.offset
        a,b,c,d = box
        return a*self.scale+ox,b*self.scale+oy,c*self.scale+ox,d*self.scale+oy

    def to_image(self,x,y):
        ox,oy = self.offset
        w,h = self.original.size
        return max(0,min(w,round((x-ox)/self.scale))),max(0,min(h,round((y-oy)/self.scale)))

    def press(self,event):
        if self.busy or self.original is None:
            return
        self.show_result = False
        self.draw()
        self.start_point = self.to_image(event.x,event.y)

    def drag(self,event):
        if self.busy or not getattr(self,'start_point',None):
            return
        x,y = self.to_image(event.x,event.y)
        a,b = self.start_point
        self.canvas.delete('drag')
        self.canvas.create_rectangle(*self.to_canvas((a,b,x,y)),outline='#ffda7a',width=2,tags='drag')

    def release(self,event):
        if self.busy or not getattr(self,'start_point',None):
            return
        a,b = self.start_point
        x,y = self.to_image(event.x,event.y)
        self.start_point = None
        box = (min(a,x),min(b,y),max(a,x),max(b,y))
        if box[2]-box[0] >= 3 and box[3]-box[1] >= 3:
            self.boxes.append(box)
        self.draw()
        self.status.set(f'已选择 {len(self.boxes)} 个水印区域')

    def undo(self):
        if self.boxes:
            self.boxes.pop()
        self.show_result = False
        self.draw()

    def clear(self):
        self.boxes = []
        self.show_result = False
        self.draw()

    def preview(self):
        if self.original is None or not self.boxes:
            self.status.set('请先选择图片并框选水印')
            return
        if self.duration is not None:
            self.status.set('视频可拖动进度条检查选框；处理效果请导出后查看。')
            return
        if self.show_result:
            self.show_result=False;self.draw();self.status.set('显示原图与选框');return
        original,boxes=self.original,list(self.boxes)
        def job():
            from core import image_restore
            self.events.put(('preview_ready',image_restore(original,boxes)))
            return '修复预览已生成；再次点击查看原图。'
        self.run_job(job)

    def start_restore(self):
        if not self.source or not self.boxes:
            messagebox.showinfo('需要选框','请先选择本地图片或视频，并拖动框选水印。')
            return
        try:
            folder = self.output_dir()
        except Exception as error:
            messagebox.showerror('检查保存位置',str(error))
            return
        source,boxes = self.source,list(self.boxes)
        def job():
            from core import restore
            out = restore(source,folder,boxes,self.cancel,self.emit_progress)
            self.emit_log('已保存：'+str(out))
            return '处理完成。点击“打开文件夹”查看。'
        self.run_job(job)

    def stop(self):
        self.cancel.set()
        self.status.set('正在取消… 网络请求可能需要等待超时返回。')
        self.stop_btn.configure(state='disabled')

    def close(self):
        if self.busy:
            self.closing = True
            self.stop()
            self.status.set('正在取消并清理临时文件，完成后自动关闭…')
        else:
            self.shutdown()

    def shutdown(self):
        if getattr(self,'_shutdown_pending',False):return
        self.saved_settings.update({'folder':self.folder.get(),'mute':self.mute.get()})
        if self.collector_panel:
            self.saved_settings.update(self.collector_panel.settings())
        if self.facebook_panel:
            self.saved_settings.update(self.facebook_panel.settings())
        try:save_settings(CONFIG, self.saved_settings)
        except OSError:self.add_log('设置未能保存，请检查程序目录是否可写。')
        if self.facebook_panel and self.facebook_panel.service:
            self.facebook_panel.service.browser.shutdown()
        services=[]
        if getattr(self,'x_service',None):services.append(self.x_service.browser)
        if getattr(self,'collector_service',None):services.append(self.collector_service.browser)
        if self.instagram_service:services.append(self.instagram_service)
        if services:
            self._shutdown_pending=True;self.set_busy(True)
            self.status.set('正在关闭清影浏览器并断开连接…')
            for service in services:service.shutdown()
            def finish():
                if any(service.thread.is_alive() for service in services):self.after(100,finish)
                else:self.destroy()
            self.after(100,finish)
        else:self.destroy()

if __name__ == '__main__':
    if '--glass-window' in sys.argv:
        from glass_host import glass_main
        glass_main()
        raise SystemExit
    if len(sys.argv)==3 and sys.argv[1]=='--diagnose-facebook':
        from facebook_diagnostics import check
        check(Path(sys.argv[2]))
        raise SystemExit
    if len(sys.argv)==2 and sys.argv[1]=='--facebook-browser':
        from facebook_browser import browser_main
        browser_main()
        raise SystemExit
    if len(sys.argv) == 4 and sys.argv[1] == '--diagnose-instagram':
        from diagnostics import instagram_check
        instagram_check(sys.argv[2], sys.argv[3])
        raise SystemExit
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    application=App()
    if '--facebook-home' in sys.argv:application.show_page('facebook')
    if '--classic' in sys.argv:
        application.mainloop()
    else:
        from glass_host import GlassHost
        application.withdraw()
        host=GlassHost(application,'facebook' if '--facebook-home' in sys.argv else 'download')
        try:application.mainloop()
        finally:host.close()

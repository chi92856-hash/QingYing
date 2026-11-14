"""A dedicated persistent WebView2 window with authenticated loopback IPC.

No web page receives a Python API or the IPC secret. The browser owns only its
own login directory and never reads the user's Edge or Codex browser profile.
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from multiprocessing.connection import Listener, Client
from common import LocalRPC


def facebook_url(url):
    p=urlparse(url)
    return p.scheme=='https' and (p.hostname or '').lower() in ('www.facebook.com','facebook.com','m.facebook.com','web.facebook.com')


SITES = {
    'instagram': ('Instagram', 'https://www.instagram.com/', {'instagram.com', 'www.instagram.com'}),
    'x': ('X', 'https://x.com/', {'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com'}),
    'facebook': ('Facebook', 'https://www.facebook.com/', {'facebook.com', 'www.facebook.com', 'm.facebook.com', 'web.facebook.com'}),
    'collector': ('小红书', 'https://www.xiaohongshu.com/', {'xiaohongshu.com', 'www.xiaohongshu.com'}),
}
CDP_SITES = {'collector', 'x', 'instagram'}


class EmbeddedFacebook:
    def __init__(self, data_dir, site='facebook'):
        if site not in SITES:raise ValueError('未知内置浏览器站点')
        self.site=site
        self.data_dir=Path(data_dir).resolve()
        self.connection=None;self.process=None;self.lock=threading.Lock()
        self.rpc=None

    def ensure(self):
        if self.process and self.process.poll() is None and self.connection:return
        self.data_dir.mkdir(parents=True,exist_ok=True)
        key=secrets.token_bytes(32)
        listener=Listener(('127.0.0.1',0),authkey=key)
        env=os.environ.copy()
        config={'port':listener.address[1],'key':key.hex(),'data':str(self.data_dir),'site':self.site}
        if self.site in CDP_SITES:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));config['cdp_port']=probe.getsockname()[1]
            # This endpoint controls only this app-owned WebView2 session.
            env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=f"--remote-debugging-address=127.0.0.1 --remote-debugging-port={config['cdp_port']}"
        env['QINGYING_FB_BROWSER']=json.dumps(config)
        entry=Path(__file__).with_name('app.py')
        cmd=[sys.executable,'--facebook-browser'] if getattr(sys,'frozen',False) else [sys.executable,str(entry),'--facebook-browser']
        # The user must be able to log in to and inspect this interactive window.
        self.process=subprocess.Popen(cmd,env=env,creationflags=0x08000000 if os.name=='nt' else 0)
        accepted=[]
        def accept():
            try:accepted.append(listener.accept())
            except (OSError,EOFError):pass
        worker=threading.Thread(target=accept,daemon=True);worker.start()
        worker.join(35)
        listener.close()
        if not accepted:raise ValueError('清影内置浏览器启动失败，请确认系统已安装 Edge WebView2 Runtime。')
        self.connection=accepted[0]
        self.rpc=LocalRPC(self.connection,60,'内置浏览器页面响应超时，请检查窗口中的登录或验证提示。')

    def call(self,op,value=None):
        with self.lock:
            self.ensure()
            try:
                result=self.rpc.request((op,value))
            except TimeoutError:
                raise
            except (OSError,EOFError):
                self.connection=None;self.rpc=None
                raise ValueError('内置浏览器已关闭，请重新打开后继续。') from None
            if 'error' in result:raise ValueError(result['error'])
            return result.get('value')

    def goto(self,url):
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in SITES[self.site][2]:raise ValueError('请输入当前站点的 HTTPS 链接。')
        return self.call('goto',url)

    def evaluate(self,script):return self.call('evaluate',script)

    def shutdown(self):
        if self.connection:
            try:self.connection.send(('close',None))
            except (OSError,EOFError):pass
            self.connection.close();self.connection=None;self.rpc=None


def browser_main():
    config=json.loads(os.environ.pop('QINGYING_FB_BROWSER'))
    import webview
    site=config.get('site','facebook')
    if site not in SITES:raise ValueError('未知内置浏览器站点')
    label,home,hosts=SITES[site]
    if site in CDP_SITES:
        webview.settings['REMOTE_DEBUGGING_PORT']=int(config['cdp_port'])
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=False
    def allowed(url):
        parsed=urlparse(url)
        return parsed.scheme=='https' and (parsed.hostname or '').lower() in hosts
    window=webview.create_window(f'清影 · {label} 内置浏览器（登录状态自动保留）',home,width=1120,height=820)
    details=[]
    def worker():
        connection=Client(('127.0.0.1',int(config['port'])),authkey=bytes.fromhex(config['key']))
        while True:
            if window.events.closed.is_set():break
            if not connection.poll(.3):continue
            try:op,value=connection.recv()
            except (OSError,EOFError):break
            try:
                if op=='close':window.destroy();break
                if op=='endpoint' and site in CDP_SITES:
                    if not window.events.shown.wait(20):raise TimeoutError('内置浏览器窗口未能初始化。')
                    port=int(config['cdp_port']);deadline=time.monotonic()+20
                    while True:
                        try:
                            with socket.create_connection(('127.0.0.1',port),timeout=.5):break
                        except OSError:
                            if window.events.closed.is_set() or time.monotonic()>=deadline:
                                raise TimeoutError('内置浏览器自动操作连接未就绪，请关闭内置窗口后重试。')
                            time.sleep(.1)
                    result=f"http://127.0.0.1:{port}"
                elif op=='detail' and site=='collector':
                    details[:]=[page for page in details if not page.events.closed.is_set()]
                    if not details:
                        details.append(webview.create_window('清影 · 小红书作品详情',url='about:blank',width=1000,height=780))
                    if not details[0].events.shown.wait(20):raise TimeoutError('作品详情窗口未能初始化。')
                    result=True
                elif op=='goto':
                    if not allowed(value):raise ValueError('只允许当前站点页面')
                    if not window.events.loaded.is_set() or window.get_current_url()!=value:
                        window.load_url(value)
                        if not window.events.loaded.wait(35):raise TimeoutError(label+' 页面加载超时，请检查网络或登录提示。')
                    result=True
                elif op=='evaluate':
                    if not allowed(window.get_current_url() or ''):raise ValueError('当前窗口不在'+label+'，请返回主页后重试。')
                    result=window.evaluate_js(value)
                elif op=='click':
                    if not allowed(window.get_current_url() or ''):raise ValueError('当前窗口不在'+label+'。')
                    # Send trusted input within this owned WebView only. This
                    # does not move the user's desktop mouse or open a debug port.
                    from webview.platforms.winforms import BrowserView
                    from System import Action
                    form=BrowserView.instances[window.uid]
                    for event in ('mousePressed','mouseReleased'):
                        tasks=[]
                        payload=json.dumps({'type':event,'x':float(value['x']),'y':float(value['y']),
                                            'button':'left','clickCount':1})
                        def send():
                            tasks.append(form.webview.CoreWebView2.CallDevToolsProtocolMethodAsync('Input.dispatchMouseEvent',payload))
                        form.Invoke(Action(send))
                        tasks[0].GetAwaiter().GetResult()
                    result=True
                elif op=='cookies':
                    if not allowed(window.get_current_url() or ''):raise ValueError('请在内置浏览器打开'+label+'。')
                    result=[]
                    for cookie in window.get_cookies():
                        for name,morsel in cookie.items():
                            domain=morsel['domain']
                            if domain.lstrip('.').lower() in hosts:
                                result.append(dict(name=name,value=morsel.value,domain=domain,path=morsel['path'] or '/',secure=bool(morsel['secure'])))
                elif op=='show':window.show();result=True
                else:raise ValueError('不支持的浏览器操作')
                connection.send({'value':result})
            except Exception as e:
                try:connection.send({'error':str(e)[:500]})
                except (OSError,EOFError):break
        connection.close()
        for page in details+[window]:
            try:page.destroy()
            except Exception:pass
    webview.start(worker,gui='edgechromium',private_mode=False,storage_path=config['data'])

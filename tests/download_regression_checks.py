"""Offline checks for cookie selection, cancellation state and repeatable EXE updates."""
from pathlib import Path
import sys
import threading
import time
import types
import marshal
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'tools')]
import instagram_support as instagram
from common import Cancelled
from update_bundle import update_app


def check_downloads(start_method=None):
    original_core=sys.modules.get('core')
    core=types.ModuleType('core')
    attempts=[]
    class Downloader:
        def __init__(self,event,log,progress=None,cookie_file='',**kwargs):
            self.event=event;self.log=log;self.session=types.SimpleNamespace(close=lambda:None)
        def download(self,url,folder):
            attempts.append(url)
            if url.endswith('/cancel/'):
                self.event.set();raise Cancelled('cancelled')
            if url.endswith('/between/'):
                self.event.set()
            return [Path('saved.jpg')]
    core.Downloader=Downloader
    core.share_urls=lambda text:text.splitlines()
    core.social_platform=lambda url:'Instagram'
    def check_cancel(event):
        if event.is_set():raise Cancelled('cancelled')
    core.check_cancel=check_cancel
    sys.modules['core']=core
    try:
        if start_method is None:
            module=compile((ROOT/'source/app.py').read_text('utf-8'),'app.py','exec')
            app_class=next(c for c in module.co_consts if isinstance(c,types.CodeType) and c.co_name=='App')
            start_method=next(c for c in app_class.co_consts if isinstance(c,types.CodeType) and c.co_name=='start_download')
        start=types.FunctionType(start_method,{'time':time})
        class App:
            def __init__(self,cookie='selected-cookies.txt',retry_at=0,urls=None):
                self.pending_urls=[];self.instagram_retry_at=retry_at;self.cancel=threading.Event()
                self.messages=[];self.events=types.SimpleNamespace(put=self.messages.append)
                self.links=types.SimpleNamespace(get=lambda *a:'\n'.join(urls or ['https://www.instagram.com/p/test/']))
                self.cookie=types.SimpleNamespace(get=lambda:cookie)
                self.mute=types.SimpleNamespace(get=lambda:False)
            def output_dir(self):return ROOT
            def emit_log(self,*args):pass
            def emit_progress(self,*args):pass
            def get_instagram_service(self):raise instagram.InstagramAccessError('内置浏览器未连接')
            def run_job(self,job):self.result=job()
        app=App();start(app)
        assert len(attempts)==1 and app.result.startswith('完成')
        attempts.clear();app=App(cookie='');start(app)
        assert not attempts and app.result.startswith('已暂停 Instagram')
        attempts.clear();app=App(retry_at=time.time()+300);start(app)
        assert not attempts and app.result.startswith('已暂停 Instagram')
        first='https://www.instagram.com/p/first/'
        second='https://www.instagram.com/p/cancel/'
        third='https://www.instagram.com/p/last/'
        app=App(urls=[first,second,third]);app.pending_urls=[first,second,third]
        start(app)
        state=next(payload for kind,payload in app.messages if kind=='download_state')
        assert state[0]==[second,third] and app.result.startswith('已取消')
        # Cancellation before starting, between links, and while rate-limited.
        for urls,preset,blocked,expected in [([first,second],True,None,[first,second]),
                (['https://www.instagram.com/p/between/',third],False,None,[third]),
                ([second,third],False,instagram.InstagramRateLimited(time.time()+300),[second,third])]:
            event=threading.Event()
            if preset:event.set()
            downloader=Downloader(event,lambda *a:None)
            if blocked:
                # First blocked link skips the downloader; cancel before second iteration.
                class CancelOnSecondCheck:
                    calls=0
                    def is_set(self):self.calls+=1;return self.calls>1
                downloader.event=CancelOnSecondCheck()
            result=instagram.download_batch(downloader,urls,ROOT,blocked=blocked)
            assert result.cancelled and result.pending==expected
            if blocked:assert result.blocked is blocked
        print('PASS: selected cookies work without Edge; missing cookies and cooldown still block')
        print('PASS: cancellation preserves remaining URLs and removes successful resumed links')
    finally:
        if original_core is None:sys.modules.pop('core',None)
        else:sys.modules['core']=original_core


def check_updates():
    original=compile('class App:\n def __init__(self):pass\n def run_job(self):pass\n def shutdown(self):pass\n def start_download(self):pass\nSTARTUP="CLASSIC_STARTUP_SENTINEL"\n','app.py','exec')
    first=update_app(marshal.dumps(original))
    second=update_app(first)
    for payload in (first,second):
        wrapper=marshal.loads(payload)
        entry=marshal.loads(next(c for c in wrapper.co_consts if isinstance(c,bytes)))
        assert '--classic' in entry.co_consts and '--glass-window' in entry.co_consts
        assert 'GlassHost' in entry.co_names
        app=next(c for c in entry.co_consts if isinstance(c,types.CodeType) and c.co_name=='App')
        method=next(c for c in app.co_consts if isinstance(c,types.CodeType) and c.co_name=='start_download')
        assert 'cancelled' in next(c for c in method.co_consts if isinstance(c,types.CodeType) and c.co_name=='job').co_names
    try:update_app(marshal.dumps(compile('x=1','unknown.py','exec')))
    except ValueError:pass
    else:raise AssertionError('Unknown entrypoint should fail explicitly')
    print('PASS: two consecutive updates retain webview/classic CLI modes and latest download method')


if __name__=='__main__':
    check_downloads()
    check_updates()


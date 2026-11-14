"""Offline checks for the collector's built-in WebView2 connection and search input."""
import ast
from pathlib import Path
import sys
import types
from threading import Event
from urllib.parse import urlparse,urlencode,parse_qs
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))

def check_browser(worker_class=None):
    if worker_class is None:
        tree=ast.parse((ROOT/'source/collector.py').read_text('utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BrowserWorker')
        namespace={'LoginRequired':ValueError,'urlparse':urlparse,'urlencode':urlencode,'check_cancel':lambda event:None}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'collector.BrowserWorker','exec'),namespace)
        worker_class=namespace['BrowserWorker']
    operations=[]
    class Locator:
        def fill(self,value):operations.append(('fill',value))
        def press(self,value):operations.append(('press',value))
    class Page:
        url='https://www.xiaohongshu.com/'
        def is_closed(self):return False
        def on(self,*args):pass
        def set_default_timeout(self,*args):pass
        def goto(self,url,**kwargs):operations.append(('goto',url))
        def locator(self,selector):assert selector=='#search-input';return Locator()
        def wait_for_timeout(self,*args):pass
        def bring_to_front(self):operations.append(('focus',))
    main=Page();detail=Page()
    context=types.SimpleNamespace(pages=[main])
    def new_page():raise AssertionError('Must use a WebView2 target, not create an external browser page')
    context.new_page=new_page
    class Embedded:
        def call(self,op):
            operations.append(('ipc',op))
            if op=='endpoint':return 'http://127.0.0.1:12345'
            if op=='detail':context.pages.append(detail)
    def connect(endpoint,timeout):
        assert endpoint=='http://127.0.0.1:12345'
        return types.SimpleNamespace(contexts=[context])
    worker=worker_class.__new__(worker_class)
    worker.context=None;worker.page=None;worker.embedded=Embedded()
    worker.playwright=types.SimpleNamespace(chromium=types.SimpleNamespace(connect_over_cdp=connect))
    worker.log=lambda *a:None
    worker._ensure()
    assert worker.page is main
    worker._gated=lambda page:False
    worker._wait_results=lambda cancel,before:operations.append(('results',before))
    worker._start_search('测试关键词',Event())
    assert ('fill','测试关键词') in operations and ('press','Enter') in operations
    fallback=next(value for op,value in [x for x in operations if len(x)==2] if op=='goto' and '/search_result?' in value)
    assert parse_qs(urlparse(fallback).query)['keyword']==['测试关键词']
    assert worker._detail_page() is detail
    assert worker._detail_page() is detail
    assert operations.count(('ipc','detail'))==1
    assert '内置浏览器' in worker._login()
    login_page=types.SimpleNamespace(url='https://www.xiaohongshu.com/explore',
        locator=lambda selector:types.SimpleNamespace(inner_text=lambda **kw:'登录后推荐更懂你的笔记'),
        bring_to_front=lambda:operations.append(('login_focus',)))
    try:worker_class._gated(worker,login_page)
    except ValueError as error:assert '登录' in str(error)
    else:raise AssertionError('Login modal must stop search with a clear message')
    assert ('login_focus',) in operations
    print('PASS: collector connects to the embedded target and automatically fills/submits search')
    print('PASS: details stay in an embedded window and reuse the same target')

if __name__=='__main__':check_browser()

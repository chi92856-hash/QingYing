"""Bounded cover fetches and in-place UI updates without selection loss."""
import ast
from pathlib import Path
import sys
import types
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))

def check_thumbnails(fetch=None,handler=None):
    if fetch is None:
        tree=ast.parse((ROOT/'source/collector.py').read_text('utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='download_cover')
        ns={'urlparse':urlparse}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'collector.cover','exec'),ns)
        fetch=ns['download_cover']
    g=fetch.__globals__;old_requests=g.get('requests');old_time=g.get('time')
    old_core=sys.modules.get('core');sys.modules['core']=types.SimpleNamespace(DESKTOP_UA='test')
    data=[b'cover'];content=['image/png'];calls=[]
    class Response:
        @property
        def headers(self):return {'Content-Type':content[0]}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_content(self,size):return iter(data)
    class Session:
        def __init__(self):self.proxies={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,**kwargs):calls.append((url,kwargs));return Response()
    g.update(requests=types.SimpleNamespace(Session=Session),time=types.SimpleNamespace(monotonic=lambda:0))
    try:
        assert fetch('http://sns-webpic.xhscdn.com/cover')==b'cover'
        assert calls[-1][0].startswith('https://') and calls[-1][1]['allow_redirects'] is False
        assert calls[-1][1]['headers']['Referer']=='https://www.xiaohongshu.com/'
        assert fetch('https://xhscdn.com.evil.example/image')==b'' and len(calls)==1
        content[0]='text/html';assert fetch('https://sns-webpic.xhscdn.com/image')==b''
        content[0]='image/png';data[:]=[b'x'*2_000_001]
        assert fetch('https://sns-webpic.xhscdn.com/image')==b''
    finally:
        g['requests']=old_requests;g['time']=old_time
        if old_core is None:sys.modules.pop('core',None)
        else:sys.modules['core']=old_core
    if handler is None:
        code=compile((ROOT/'source/collector_ui.py').read_text('utf-8'),'collector_ui.py','exec')
        cls=next(c for c in code.co_consts if isinstance(c,types.CodeType) and c.co_name=='CollectorPanel')
        handler=next(c for c in cls.co_consts if isinstance(c,types.CodeType) and c.co_name=='handle_thumbnail')
    method=types.FunctionType(handler,{})
    changes=[];item=types.SimpleNamespace(identifier='note',thumbnail_bytes=b'')
    panel=types.SimpleNamespace(items=[item],thumbnails={'note':types.SimpleNamespace(configure=lambda **kw:changes.append(kw))},
        selected={'note':True},_thumbnail_image=lambda data:'image' if data==b'cover' else None)
    method(panel,('old-result',b'cover'));assert not changes
    method(panel,('note',b'cover'))
    assert changes==[dict(image='image',text='')] and panel.selected['note'] is True
    assert item.thumbnail_bytes==b'cover'
    print('PASS: cover URL/size/type limits, CDN headers, stale-result handling and selection-preserving image updates')

if __name__=='__main__':check_thumbnails()

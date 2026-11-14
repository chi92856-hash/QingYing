"""Direct keyword search: first five web results, no per-note verification."""
import ast
from pathlib import Path
import sys
import time
import types
from threading import Event
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))
from common import Cancelled

def check_search(worker_class=None):
    if worker_class is None:
        tree=ast.parse((ROOT/'source/collector.py').read_text('utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BrowserWorker')
        ns={}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'collector.search','exec'),ns)
        worker_class=ns['BrowserWorker']
    g=worker_class._search.__globals__
    names=('time','History','note_id','check_cancel')
    old={key:g.get(key) for key in names}
    def forbidden(*a,**kw):raise AssertionError('Search must not verify or resolve notes')
    def cancel(event):
        if event.is_set():raise Cancelled('任务已取消')
    g.update(time=time,History=forbidden,note_id=lambda url:url.rsplit('/',1)[-1],check_cancel=cancel)
    def run(excluded=(),empty=False,cancel_after=None):
        event=Event();updates=[];queries=[];scrolls=[]
        order=['3','1','4','0','2','5']
        cards={i:types.SimpleNamespace(identifier=i,url='https://www.xiaohongshu.com/explore/'+i,thumbnail='',thumbnail_bytes=b'') for i in order}
        w=worker_class.__new__(worker_class);w.signature=None;w.search_cache={}
        w._ensure=lambda:None;w._gated=lambda page:None;w._resolve=forbidden
        w.page=types.SimpleNamespace(mouse=types.SimpleNamespace(wheel=lambda *a:scrolls.append(a)),wait_for_timeout=lambda *a:None)
        def start(query,event):queries.append(query);w.search_cache.update({} if empty else cards)
        w._start_search=start;w._apply_filters=lambda *a:None
        w._dom_cards=lambda:[{'url':cards[i].url} for i in order]
        def publish(items,counts):
            updates.append(([x.identifier for x in items],dict(counts)))
            if cancel_after and len(items)==cancel_after:event.set()
        try:items,counts=w._search('关键词','附加词','图片','综合',set(excluded),ROOT/'unused.db',event,on_update=publish)
        except Cancelled:items=None;counts=None
        return items,counts,updates,queries,scrolls
    try:
        items,counts,updates,queries,_=run()
        assert [x.identifier for x in items]==['3','1','4','0','2']
        assert queries==['关键词 附加词'] and any(len(x)==1 and c['searching'] for x,c in updates)
        assert updates[-1][1]['searching'] is False
        items,_,_,_,_=run(excluded=['3'])
        assert [x.identifier for x in items]==['1','4','0','2','5']
        items,counts,_,_,scrolls=run(empty=True)
        assert items==[] and counts['reason'] and len(scrolls)<=8
        items,_,updates,_,_=run(cancel_after=2)
        assert items is None and len(updates[-1][0])==2 and updates[-1][1]['searching'] is False
        print('PASS: first five webpage results in order; no detail/history verification; bounded empty search; cancellation')
    finally:
        for key,value in old.items():
            if value is None:g.pop(key,None)
            else:g[key]=value

def check_panel(method=None):
    if method is None:
        code=compile((ROOT/'source/collector_ui.py').read_text('utf-8'),'collector_ui.py','exec')
        cls=next(c for c in code.co_consts if isinstance(c,types.CodeType) and c.co_name=='CollectorPanel')
        method=next(c for c in cls.co_consts if isinstance(c,types.CodeType) and c.co_name=='handle_batch')
    handler=types.FunctionType(method,{})
    summaries=[];renders=[]
    panel=types.SimpleNamespace(items=[],seen=set(),summary=types.SimpleNamespace(set=summaries.append),_render=lambda:renders.append(True))
    item=types.SimpleNamespace(identifier='candidate')
    handler(panel,([item],dict(searching=True,read=1,reason=''),'图片'))
    handler(panel,([item],dict(searching=True,read=1,reason=''),'图片'))
    assert len(renders)==1 and '正在搜索' in summaries[-1]
    handler(panel,([item],dict(searching=False,read=1,reason=''),'图片'))
    assert len(renders)==2 and '搜索完成' in summaries[-1]
    print('PASS: search results render immediately and final status reports completion')

if __name__=='__main__':
    check_search()
    check_panel()

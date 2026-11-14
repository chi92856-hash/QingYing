"""Focused X parsing, thread filtering and explicit-selection checks."""
from pathlib import Path
import ast
import sys
import tempfile
from threading import Event
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'source'))
from x_support import post_url, profile_url, original_image, tweet_media, XBrowser, XService
from core import share_urls, social_platform


def main():
    assert post_url('https://twitter.com/user/status/123/photo/1')[1] == '123'
    assert social_platform('https://x.com/u/status/123') == 'X'
    assert profile_url('https://twitter.com/Test_User/media?x=1') == ('https://x.com/Test_User','Test_User')
    for value in ['https://x.com/home','https://x.com/u/status/123','https://x.com.evil.test/u','http://x.com/u']:
        try: profile_url(value)
        except ValueError: pass
        else: raise AssertionError(value)
    assert share_urls('https://x.com/u/status/123') == ['https://x.com/u/status/123']
    for value in ['https://x.com.evil.test/u/status/123', 'http://x.com/u/status/123', 'https://x.com/home']:
        try: post_url(value)
        except ValueError: pass
        else: raise AssertionError(value)
    assert original_image('https://pbs.twimg.com/media/ABC.jpg') == 'https://pbs.twimg.com/media/ABC?format=jpg&name=orig'
    assert not original_image('https://evil.test/media/ABC.jpg')
    photo = {'type':'photo','media_url_https':'https://pbs.twimg.com/media/ABC.jpg'}
    assert tweet_media({'extended_entities':{'media':[photo]}})[0].kind == 'image'
    video = {'type':'video','video_info':{'variants':[
        {'bitrate':1,'content_type':'video/mp4','url':'https://video.twimg.com/a.mp4'},
        {'bitrate':9,'content_type':'video/mp4','url':'https://video.twimg.com/b.mp4'},
        {'bitrate':99,'content_type':'video/mp4','url':'https://evil.test/b.mp4'}]}}
    assert tweet_media({'extended_entities':{'media':[video]}})[0].urls == ['https://video.twimg.com/b.mp4','https://video.twimg.com/a.mp4']
    worker = XBrowser.__new__(XBrowser)
    worker.log = lambda message:None
    worker.tweets = {}; worker._ensure = lambda: None
    data = {'100':{'full_text':'root'}, '101':{'full_text':'reply','in_reply_to_status_id_str':'100','extended_entities':{'media':[photo]}},
            '102':{'full_text':'unrelated','in_reply_to_status_id_str':'999','extended_entities':{'media':[photo]}},
            '103':{'full_text':'nested','in_reply_to_status_id_str':'101','extended_entities':{'media':[photo]}}}
    worker.page = SimpleNamespace(url='https://x.com/i/status/100', goto=lambda *a,**k:worker.tweets.update(data),
        wait_for_timeout=lambda ms:None, mouse=SimpleNamespace(wheel=lambda *a:None))
    items = worker._scan('https://x.com/u/status/100', True, Event())
    assert {i.identifier for i in items} == {'101_0','103_0'}
    worker.tweets = {}; worker.authors = {}
    nodes = {'data': [
        {'rest_id':'201','legacy':{'full_text':'own','extended_entities':{'media':[photo, photo]}},
         'core':{'user_results':{'result':{'core':{'screen_name':'Test_User'}}}}},
        {'rest_id':'202','legacy':{'full_text':'recommendation','extended_entities':{'media':[photo]}},
         'core':{'user_results':{'result':{'legacy':{'screen_name':'Other'}}}}},
        {'rest_id':'203','legacy':{'full_text':'unknown author','extended_entities':{'media':[photo]}}}]}
    worker.page = SimpleNamespace(url='https://x.com/Test_User',
        goto=lambda *a,**k:worker._response(SimpleNamespace(url='https://x.com/i/api/graphql/test/UserMedia', json=lambda:nodes)),
        wait_for_timeout=lambda ms:None,mouse=SimpleNamespace(wheel=lambda *a:None),evaluate=lambda script:[])
    profile_items = worker._profile_scan('https://x.com/test_user', Event())
    assert {i.identifier for i in profile_items} == {'201_0','201_1'}
    assert all(i.author == 'test_user' and i.asset.kind == 'image' for i in profile_items)
    worker.page.goto = lambda *a,**k:None
    worker.page.evaluate = lambda script:[
        {'post':'https://x.com/Test_User/status/301','href':'https://x.com/Test_User/status/301/photo/1','src':'https://pbs.twimg.com/media/DOM.jpg','title':'DOM image'},
        {'post':'https://x.com/Other/status/302','href':'https://x.com/Other/status/302/photo/1','src':'https://pbs.twimg.com/media/AD.jpg'},
        {'post':'https://x.com/Test_User/status/303','href':'https://x.com/Test_User/status/303/photo/1','src':'https://evil.test/media/BAD.jpg'}]
    dom_items = worker._profile_scan('https://x.com/test_user', Event())
    assert [item.identifier for item in dom_items] == ['301_0'], 'DOM-only profiles must work without Tweet JSON'
    cancelled = Event(); cancelled.set()
    from common import Cancelled
    try: worker._profile_scan('https://x.com/test_user', cancelled)
    except Cancelled: pass
    else: raise AssertionError('Profile retrieval must honor cancellation')
    with tempfile.TemporaryDirectory(dir=ROOT) as folder:
        service = XService.__new__(XService)
        from collector import History
        service.history = History(Path(folder)/'history.db')
        service.log = lambda *a:None; service.progress = lambda *a:None
        assert service.download([],folder,'图片',False,Event()) == ([],[],0)
        assert not list(Path(folder).glob('*.jpg'))
    tree = ast.parse((ROOT/'source/x_ui.py').read_text('utf-8'))
    panel = next(n for n in tree.body if isinstance(n,ast.ClassDef))
    search = next(n for n in panel.body if isinstance(n,ast.FunctionDef) and n.name=='search')
    assert not any(isinstance(n,ast.Attribute) and n.attr in {'download','fetch','fetch_many'} for n in ast.walk(search))
    for path in (ROOT/'source').glob('*.py'): compile(path.read_text('utf-8'),str(path),'exec')
    print('PASS: X URL/media validation, original images, highest-quality MP4, reply ancestry, no automatic downloads, syntax')


if __name__ == '__main__': main()

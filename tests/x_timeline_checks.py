"""Collect profile post photos after many text-only posts, without media navigation."""
from threading import Event
from types import SimpleNamespace
from x_support import XBrowser


def check():
    worker = XBrowser.__new__(XBrowser)
    worker._ensure = lambda:None
    worker.log = lambda message:None
    state = {'scrolls':0, 'destinations':[]}
    def rows(script):
        assert 'main article' in script and 'time' in script
        index = min(state['scrolls'], 12)
        post = f'https://x.com/test_user/status/{500+index}'
        if index < 12: return [{'post':post,'href':post,'src':''}]
        return [
            {'post':post,'href':post+'/photo/1','src':'https://pbs.twimg.com/media/ONE.jpg'},
            {'post':post,'href':post+'/photo/2','src':'https://pbs.twimg.com/media/TWO.png'},
            {'post':post,'href':'https://x.com/test_user/status/999/photo/1','src':'https://pbs.twimg.com/media/QUOTE.jpg'},
            {'post':'https://x.com/other/status/700','href':'https://x.com/other/status/700/photo/1','src':'https://pbs.twimg.com/media/OTHER.jpg'}]
    def scroll(*args): state['scrolls'] += 1
    worker.page = SimpleNamespace(url='https://x.com/test_user',
        goto=lambda url,**kw:state['destinations'].append(url), evaluate=rows,
        wait_for_timeout=lambda ms:None, mouse=SimpleNamespace(wheel=scroll))
    results = worker._profile_scan('https://x.com/test_user/media', Event())
    assert state['destinations'] == ['https://x.com/test_user']
    assert {item.identifier for item in results} == {'512_0','512_1'}
    assert len(worker.profile_posts) == 13
    print('PASS: profile Posts only; continues past text posts; multiple photos; quote/repost exclusion')

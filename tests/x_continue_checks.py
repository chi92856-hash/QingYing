"""Offline continuation, media filtering and cancellation regressions."""
from threading import Event
from types import SimpleNamespace
from common import Cancelled
from x_support import XBrowser
from x_ui import XPanel


def worker_for(rows, on_wait=None):
    worker = XBrowser.__new__(XBrowser)
    worker._ensure = lambda: None
    worker.log = lambda message: None
    state = {'frame': 0, 'navigations': 0}
    def goto(url, **kwargs):
        state['navigations'] += 1
        state['frame'] = 0
        worker.page.url = url
    def wheel(*args):
        state['frame'] = min(99, state['frame'] + 1)
    worker.page = SimpleNamespace(url='https://x.com/test_user', goto=goto,
        wait_for_timeout=lambda ms: on_wait(worker) if on_wait else None,
        mouse=SimpleNamespace(wheel=wheel), evaluate=lambda script: rows(state['frame']))
    return worker, state


def main():
    def rows(frame):
        post = f'https://x.com/test_user/status/{1000 + frame}'
        return [dict(post=post, href=f'{post}/photo/{i+1}',
                     src=f'https://pbs.twimg.com/media/PHOTO{frame}_{i}.jpg') for i in range(4)]
    worker, state = worker_for(rows)
    first = worker._profile_scan('https://x.com/test_user', Event())
    assert len(first) == 200
    second = worker._profile_scan('https://x.com/test_user', Event(), resume=True)
    assert len(second) == 400 and len({x.identifier for x in second}) == 400
    assert state['navigations'] == 1, 'Continuation must not navigate back to the top'
    assert {x.identifier for x in first} <= {x.identifier for x in second}
    third = worker._profile_scan('https://x.com/test_user', Event(), resume=True)
    assert len(third) == 400 and '未加载' in worker.profile_stop_reason
    for url, mode in [('https://x.com/another', '图片'), ('https://x.com/test_user', '视频')]:
        try: worker._profile_scan(url, Event(), resume=True, mode=mode)
        except ValueError: pass
        else: raise AssertionError('Continuation accepted a different account or media type')
    cancelled = Event()
    def cancel_after_progress(items):
        if len(items) >= 4: cancelled.set()
    try: worker._profile_scan('https://x.com/test_user', cancelled, cancel_after_progress)
    except Cancelled: pass
    else: raise AssertionError('Cancellation ignored')
    partial = set(worker.profile_items)
    assert partial
    cancelled.clear()
    resumed = worker._profile_scan('https://x.com/test_user', cancelled, resume=True)
    assert partial <= {x.identifier for x in resumed}

    video = {'type': 'video', 'media_url_https': 'https://pbs.twimg.com/media/COVER.jpg',
             'video_info': {'variants': [
                 {'url': 'https://video.twimg.com/low.mp4', 'content_type': 'video/mp4', 'bitrate': 100},
                 {'url': 'https://video.twimg.com/high.mp4', 'content_type': 'video/mp4', 'bitrate': 900}]}}
    photo = {'type': 'photo', 'media_url_https': 'https://pbs.twimg.com/media/IMAGE.jpg'}
    def response(worker):
        worker.tweets['900'] = {'full_text': 'mixed', 'in_reply_to_status_id_str': '800', 'extended_entities': {'media': [photo, video]}}
        worker.authors['900'] = 'test_user'
    media_worker, _ = worker_for(lambda frame: [], response)
    images = media_worker._profile_scan('https://x.com/test_user', Event())
    assert [x.asset.kind for x in images] == ['image']
    videos = media_worker._profile_scan('https://x.com/test_user', Event(), mode='视频')
    assert len(videos) == 1 and videos[0].kind == '视频'
    assert videos[0].asset.urls[0] == 'https://video.twimg.com/high.mp4'
    assert videos[0].thumbnail.startswith('https://pbs.twimg.com/media/COVER?')
    mixed = media_worker._profile_scan('https://x.com/test_user', Event(), mode='图片和视频')
    assert {x.asset.kind for x in mixed} == {'image', 'video'}
    replies = media_worker._scan('https://x.com/test_user/status/800', True, Event(), mode='视频')
    assert len(replies) == 1 and replies[0].asset.kind == 'video'
    class Variable:
        def __init__(self, value=False): self.value = value
        def get(self): return self.value
        def set(self, value): self.value = value
    old = SimpleNamespace(identifier='old', thumbnail_bytes=b'cached')
    added = SimpleNamespace(identifier='new', thumbnail_bytes=b'')
    panel = SimpleNamespace(items=[old], selected={'old': Variable(True)},
        result_source='主页作品', service=None, summary=Variable(), _selection=lambda: None)
    panel._render = lambda: setattr(panel, 'selected', {item.identifier: Variable() for item in panel.items})
    replacement = SimpleNamespace(identifier='old', thumbnail_bytes=b'')
    XPanel.handle_batch(panel, [replacement, added])
    assert panel.selected['old'].get() and not panel.selected['new'].get()
    assert replacement.thumbnail_bytes == b'cached'
    print('PASS: 200→400 continuation, deduplication, same-page resume, account/type guard, cancellation, image/video filters and best MP4')


if __name__ == '__main__': main()

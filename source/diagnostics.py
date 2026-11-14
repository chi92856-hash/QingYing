"""Explicit frozen-runtime acceptance check; never writes credentials."""
import json
import threading
from pathlib import Path
from urllib.parse import urlparse


def instagram_check(url, output):
    from instagram_support import create_browser
    from core import Downloader
    from network_config import desktop_proxies
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    report = {'proxy_routes': {k: {'host': urlparse(v).hostname, 'port': urlparse(v).port}
                              for k, v in desktop_proxies().items() if k != 'no'}}
    browser = create_browser(folder / 'unused-profile', lambda _: None)
    downloader = None
    try:
        cookies = browser.call('cookies')
        report['instagram_logged_in'] = bool(cookies)
        if not cookies:
            raise ValueError('请先在日常 Edge 登录 Instagram')
        downloader = Downloader(threading.Event(), lambda _: None, lambda *a: None,
                                instagram_cookies=cookies)
        files = downloader.download(url, folder)
        report['saved'] = [{'path': str(p), 'bytes': p.stat().st_size} for p in files]
    except Exception as error:
        report['error_type'] = type(error).__name__
        report['error'] = str(error)[:1200]
    finally:
        if downloader:
            downloader.session.close()
        browser.shutdown()
        browser.thread.join(15)
        (folder / 'diagnostic.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

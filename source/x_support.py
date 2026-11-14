"""Read media from the user's app-owned X browser; never post or react."""
import re
import time
import threading
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

from collector import BrowserWorker, Candidate, History
from core import Asset, Work, Downloader, check_cancel, walk


def post_url(value):
    p = urlparse(value.strip())
    match = re.fullmatch(r'/(?:[A-Za-z0-9_]+|i/web|i)/status/(\d+)(?:/(?:photo|video)/\d+)?/?', p.path)
    if p.scheme != 'https' or p.hostname not in {'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com'} or not match:
        raise ValueError('请粘贴完整的 X 帖子 HTTPS 链接。')
    return 'https://x.com/i/status/' + match.group(1), match.group(1)


def profile_url(value):
    p = urlparse(value.strip())
    match = re.fullmatch(r'/([A-Za-z0-9_]{1,15})(?:/media)?/?', p.path)
    reserved = {'home', 'explore', 'search', 'notifications', 'messages', 'settings', 'i', 'intent', 'compose', 'login', 'logout', 'signup'}
    if p.scheme != 'https' or p.hostname not in {'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com'} or not match or match.group(1).lower() in reserved:
        raise ValueError('请粘贴 X 用户主页链接，例如 https://x.com/用户名。')
    username = match.group(1)
    return f'https://x.com/{username}', username


def original_image(value):
    p = urlparse(value)
    if p.scheme != 'https' or p.hostname != 'pbs.twimg.com' or not p.path.startswith('/media/'):
        return ''
    query = parse_qs(p.query)
    ext = (query.get('format') or [Path(p.path).suffix.lstrip('.') or 'jpg'])[0]
    if ext not in {'jpg', 'jpeg', 'png', 'webp'}:
        return ''
    path = re.sub(r'\.(?:jpg|jpeg|png|webp)$', '', p.path)
    return 'https://pbs.twimg.com' + path + '?' + urlencode({'format': ext, 'name': 'orig'})


def tweet_media(tweet):
    assets = []
    for item in (tweet.get('extended_entities') or tweet.get('entities') or {}).get('media', []):
        if item.get('type') == 'photo':
            url = original_image(item.get('media_url_https', ''))
            if url: assets.append(Asset('image', [url], 'X 原图'))
        elif item.get('type') in {'video', 'animated_gif'}:
            variants = (item.get('video_info') or {}).get('variants', [])
            urls = [v['url'] for v in sorted(variants, key=lambda v: v.get('bitrate', 0), reverse=True)
                    if v.get('content_type') == 'video/mp4' and urlparse(v.get('url', '')).scheme == 'https'
                    and urlparse(v['url']).hostname == 'video.twimg.com']
            if urls: assets.append(Asset('video', urls, 'X 源视频'))
    return assets


class XBrowser(BrowserWorker):
    def __init__(self, data_dir, log):
        self.tweets = {}
        self.authors = {}
        super().__init__(data_dir, log, embedded='x')

    def _response(self, response):
        p = urlparse(response.url)
        if p.hostname not in {'x.com', 'www.x.com', 'api.x.com', 'twitter.com', 'api.twitter.com'} or '/graphql/' not in p.path:
            return
        try:
            for node in walk(response.json()):
                legacy = node.get('legacy')
                if not isinstance(legacy, dict) or not node.get('rest_id') or 'full_text' not in legacy:
                    continue
                identifier = str(node['rest_id'])
                if identifier.isdigit():
                    self.tweets[identifier] = legacy
                    user = ((node.get('core') or {}).get('user_results') or {}).get('result') or {}
                    self.authors[identifier] = str((user.get('core') or {}).get('screen_name') or (user.get('legacy') or {}).get('screen_name') or '').casefold()
            if len(self.tweets) > 3000:
                self.tweets = dict(list(self.tweets.items())[-2000:])
                self.authors = {key: self.authors.get(key, '') for key in self.tweets}
        except Exception:
            pass

    def _gated(self, page):
        if '/i/flow/login' in page.url or '/account/access' in page.url:
            raise ValueError('请先在清影 X 内置浏览器完成登录或验证，再重新检索。')

    def _dom_profile_images(self, username):
        """Read only photos attached to posts in the main profile timeline."""
        rows = self.page.evaluate('''() => Array.from(document.querySelectorAll('main article[data-testid="tweet"]')).flatMap(article => {
            const link = Array.from(article.querySelectorAll('a[href*="/status/"]')).find(a => a.querySelector('time'));
            if (!link) return [];
            const post = link.href;
            const text = article.querySelector('[data-testid="tweetText"]')?.innerText || '';
            const images = Array.from(article.querySelectorAll('a[href*="/photo/"]')).flatMap(a =>
                Array.from(a.querySelectorAll('img')).map((img,index) => ({href:a.href, post, src:img.currentSrc || img.src, title:text || img.alt || '', index})));
            return images.length ? images : [{href:post, post, src:''}];
        })''')
        items = []
        for row in rows or []:
            post = urlparse(row.get('post', ''))
            primary = re.fullmatch(r'/([A-Za-z0-9_]+)/status/(\d+)/?', post.path)
            if post.hostname not in {'x.com','www.x.com','twitter.com','www.twitter.com'} or not primary or primary.group(1).casefold() != username.casefold(): continue
            self.profile_posts.add(primary.group(2))
            p = urlparse(row.get('href', ''))
            match = re.fullmatch(r'/([A-Za-z0-9_]+)/status/(\d+)(?:/photo/(\d+))?/?', p.path)
            if p.hostname not in {'x.com','www.x.com','twitter.com','www.twitter.com'} or not match or match.group(1).casefold() != username.casefold(): continue
            if match.group(2) != primary.group(2): continue
            image = original_image(row.get('src', ''))
            if not image: continue
            identifier = match.group(2)
            index = int(match.group(3)) - 1 if match.group(3) else int(row.get('index', 0))
            if index < 0: continue
            item = Candidate(f'{identifier}_{index}', f'https://x.com/{username}/status/{identifier}',
                             row.get('title') or 'X 主页图片', author=username, thumbnail=image)
            item.asset = Asset('image', [image], 'X 原图')
            items.append(item)
        return items

    def _login(self):
        self._ensure()
        self.embedded.call('show')
        self.page.goto('https://x.com/', wait_until='domcontentloaded', timeout=25000)
        return '请在清影 X 内置浏览器完成登录，登录状态保存在本机。'

    def _open_note(self, url):
        url, _ = post_url(url)
        self._ensure()
        self.page.goto(url, wait_until='domcontentloaded', timeout=25000)
        self.embedded.call('show')
        return '已打开 X 帖子。'

    def _scan(self, value, replies, cancel, publish=None):
        url, root = post_url(value)
        self._ensure()
        self.tweets = {}
        self.page.goto(url, wait_until='domcontentloaded', timeout=25000)
        deadline = time.monotonic() + (40 if replies else 20)
        items = {}; known = {root}; stagnant = 0
        previous = -1
        while time.monotonic() < deadline:
            check_cancel(cancel)
            self.page.wait_for_timeout(600)
            self._gated(self.page)
            # Only descendants of the requested post qualify, excluding ads and recommendations.
            for _ in range(8):
                before = len(known)
                for identifier, tweet in list(self.tweets.items()):
                    if str(tweet.get('in_reply_to_status_id_str', '')) in known: known.add(identifier)
                if len(known) == before: break
            for identifier, tweet in list(self.tweets.items()):
                if identifier not in known or (replies and identifier == root) or (not replies and identifier != root): continue
                for index, asset in enumerate(tweet_media(tweet)):
                    if replies and asset.kind != 'image': continue
                    key = f'{identifier}_{index}'
                    item = Candidate(key, 'https://x.com/i/status/' + identifier,
                                     tweet.get('full_text', '') or 'X 图片', kind='图片' if asset.kind == 'image' else '视频',
                                     thumbnail=asset.urls[0] if asset.kind == 'image' else '')
                    item.asset = asset
                    items[key] = item
            if publish: publish(list(items.values()))
            if not replies and root in self.tweets: break
            current = len(self.tweets)
            stagnant = stagnant + 1 if current == previous else 0
            previous = current
            if replies and (len(items) >= 200 or stagnant >= 10): break
            self.page.mouse.wheel(0, 850 if replies else 0)
        check_cancel(cancel)
        if not items:
            raise ValueError('未找到可访问的回复图片。请检查内置窗口的登录、验证及帖子权限。' if replies else '未取得帖子原始媒体，请检查登录、帖子权限或稍后重试。')
        return list(items.values())[:200]

    def _profile_scan(self, value, cancel, publish=None):
        url, username = profile_url(value)
        self._ensure()
        self.tweets = {}; self.authors = {}
        self.profile_posts = set()
        check_cancel(cancel)
        self.page.goto(url, wait_until='domcontentloaded', timeout=25000)
        self.log('从 X 主页帖子列表查找图片，自动跳过纯文字和视频帖子。')
        deadline = time.monotonic() + 90
        items = {}; previous = -1; stagnant = 0
        while time.monotonic() < deadline:
            check_cancel(cancel)
            self.page.wait_for_timeout(600)
            self._gated(self.page)
            for item in self._dom_profile_images(username):
                if len(items) >= 200: break
                items[item.identifier] = item
            for identifier, tweet in list(self.tweets.items()):
                # Require verified authorship: recommendations and reposted users do not qualify.
                if self.authors.get(identifier) != username.casefold(): continue
                for index, asset in enumerate(tweet_media(tweet)):
                    if asset.kind != 'image': continue
                    key = f'{identifier}_{index}'
                    item = Candidate(key, 'https://x.com/i/status/' + identifier,
                                     tweet.get('full_text', '') or 'X 主页图片', author=username, thumbnail=asset.urls[0])
                    item.asset = asset
                    items[key] = item
                    if len(items) >= 200: break
                if len(items) >= 200: break
            if publish: publish(list(items.values()))
            current = (len(self.tweets), len(items), len(self.profile_posts))
            stagnant = stagnant + 1 if current == previous else 0
            previous = current
            if len(items) >= 200 or stagnant >= 10: break
            self.page.mouse.wheel(0, 850)
        check_cancel(cancel)
        if not items:
            raise ValueError(f'已检查 {len(self.profile_posts)} 条主页帖子，未找到可访问的照片。请检查登录、账号权限或帖子中是否含图片。')
        return list(items.values())


class XService:
    def __init__(self, data_dir, log, progress):
        self.browser = XBrowser(data_dir, log)
        self.history = History(Path(data_dir) / 'history.sqlite3')
        self.log, self.progress = log, progress

    def close(self): self.browser.shutdown()
    def login(self): return self.browser.call('login')
    def open_note(self, url): return self.browser.call('open_note', url)
    def search(self, url, cancel, publish): return self.browser.call('scan', url, True, cancel, publish)
    def profile(self, url, cancel, publish): return self.browser.call('profile_scan', url, cancel, publish)

    def thumbnails(self, items, callback):
        def fetch():
            import requests
            from network_config import desktop_proxies
            with requests.Session() as session:
                session.proxies.update(desktop_proxies())
                session.trust_env = False
                for item in items:
                    if not item.thumbnail: continue
                    url = item.thumbnail.replace('name=orig', 'name=small')
                    try:
                        with session.get(url, stream=True, timeout=(3, 4), allow_redirects=False) as response:
                            response.raise_for_status()
                            if not response.headers.get('Content-Type', '').startswith('image/'): continue
                            data = bytearray()
                            for block in response.iter_content(65536):
                                data.extend(block)
                                if len(data) > 2 * 1024 * 1024: break
                            else: callback(item.identifier, bytes(data))
                    except requests.RequestException: pass
        threading.Thread(target=fetch, daemon=True, name='x-thumbnails').start()

    def download(self, items, folder, mode, mute, cancel):
        saved, failed, skipped = [], [], 0
        downloader = Downloader(cancel, self.log, self.progress, mute=mute)
        try:
            for item in items:
                check_cancel(cancel)
                if self.history.contains(item.identifier):
                    skipped += 1; continue
                try:
                    files = [downloader.fetch(item.asset, folder, 'X_' + item.identifier, item.url)]
                    self.history.mark(item, '图片', files)
                    saved.append((item, files))
                except Exception as error:
                    check_cancel(cancel)
                    failed.append((item, str(error))); self.log('图片保存失败：' + str(error))
        finally: downloader.session.close()
        return saved, failed, skipped

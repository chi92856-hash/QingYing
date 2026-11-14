"""Local media restoration and public share-page downloading."""
from __future__ import annotations
import html
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, unquote, urljoin

import requests
from PIL import Image, ImageOps
from common import Cancelled, IMAGE_EXTS

UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1'
DESKTOP_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36'
PLATFORMS = ('douyin.com', 'iesdouyin.com', 'xiaohongshu.com', 'xhslink.com',
             'instagram.com', 'facebook.com', 'fb.watch', 'fb.com', 'x.com', 'twitter.com')
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

class SourceUnavailable(ValueError):
    """Do not silently replace a missing original with a watermarked preview."""
    pass

def check_cancel(event):
    if event.is_set():
        raise Cancelled('任务已取消，未完成的临时文件已清理。')

def safe_name(value):
    value = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', str(value)).strip(' .')[:65]
    if not value or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', value, re.I):
        value = '_' + (value or '作品')
    return value

def unique_path(folder, stem, ext):
    # Each export gets a distinct name, so existing files are never overwritten.
    return Path(folder) / f'{safe_name(stem)}_{time.strftime("%Y%m%d_%H%M%S")}_{uuid.uuid4().hex[:6]}{ext}'

def share_urls(text):
    # Accept copied Markdown escapes such as https\://www\.instagram.com/…
    text = re.sub(r'\\([:./?&=_-])', r'\1', text)
    found = re.findall(r'https?://[^\s<>"\u3000]+', text)
    result = []
    for url in found:
        url = url.rstrip('.,;!。，；！）)]}》」”\'')
        host = (urlparse(url).hostname or '').lower()
        if any(host == d or host.endswith('.' + d) for d in PLATFORMS):
            if url not in result:
                result.append(url)
    if not result:
        raise ValueError('没有找到支持的作品链接。支持抖音、小红书、Instagram、Facebook 和 X，可粘贴完整分享文案。')
    return result

def social_platform(url):
    host = (urlparse(url).hostname or '').lower()
    if host in {'x.com','www.x.com','twitter.com','www.twitter.com','mobile.twitter.com'}:
        return 'X'
    if host == 'instagram.com' or host.endswith('.instagram.com'):
        return 'Instagram'
    if any(host == d or host.endswith('.' + d) for d in ('facebook.com', 'fb.watch', 'fb.com')):
        return 'Facebook'
    return None

def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk(value)

def states(page):
    """Decode only JSON data; never evaluate JavaScript from a page."""
    from yt_dlp.utils import js_to_json
    patterns = [r'window\._ROUTER_DATA\s*=', r'window\.__INITIAL_STATE__\s*=',
                r'<script[^>]+id=[\"\'](?:RENDER_DATA|__NEXT_DATA__)[\"\'][^>]*>']
    for pattern in patterns:
        for match in re.finditer(pattern, page):
            text = html.unescape(page[match.end():].split('</script>', 1)[0]).strip()
            if text.startswith('%'):
                text = unquote(text)
            try:
                yield json.JSONDecoder().raw_decode(text)[0]
            except (ValueError, TypeError):
                try:
                    yield json.JSONDecoder().raw_decode(js_to_json(text))[0]
                except (ValueError, TypeError):
                    continue

def http_urls(value):
    if isinstance(value, str):
        if value.startswith('//'):
            value = 'https:' + value
        if value.startswith(('https://', 'http://')):
            return [value]
    if isinstance(value, list):
        return [u for item in value for u in http_urls(item)]
    return []

@dataclass
class Asset:
    kind: str
    urls: list[str]
    source: str = ''

@dataclass
class Work:
    title: str
    assets: list[Asset]
    referer: str
    missing_kinds: tuple[str, ...] = ()

def parse_instagram_product(product, referer):
    """Keep images in a carousel; video-only extractors otherwise omit them."""
    if isinstance(product, list):
        product = product[0] if product else {}
    assets = []
    for item in product.get('carousel_media') or [product]:
        videos = item.get('video_versions') or []
        if videos:
            urls = [u for n in sorted(videos, key=lambda n:(n.get('width') or 0)*(n.get('height') or 0),reverse=True)
                    for u in http_urls(n.get('url'))]
            if urls:
                assets.append(Asset('video',list(dict.fromkeys(urls)),'Instagram 帖子视频'))
                continue
        # Never substitute a cover picture for a video that failed to parse.
        if str(item.get('media_type')) == '2':
            raise SourceUnavailable('Instagram 视频未返回可下载地址，未将封面图作为视频保存。')
        candidates = (item.get('image_versions2') or {}).get('candidates') or []
        urls = [u for n in sorted(candidates,key=lambda n:(n.get('width') or 0)*(n.get('height') or 0),reverse=True)
                for u in http_urls(n.get('url'))]
        if not urls:
            raise SourceUnavailable('Instagram 帖子有内容未返回下载地址，请检查登录状态和作品权限后重试。')
        assets.append(Asset('image',list(dict.fromkeys(urls)),'Instagram 帖子图片（可用最高分辨率）'))
    if not assets:
        raise SourceUnavailable('Instagram 未返回可保存的图片或视频。')
    title = product.get('title') or (product.get('caption') or {}).get('text') or 'Instagram_' + str(product.get('code') or product.get('pk') or '作品')
    return Work(title,assets,referer)

def mute_video(source, target, event):
    """Remove all audio streams without re-encoding the video."""
    import imageio_ffmpeg
    with tempfile.TemporaryFile() as errors:
        cmd = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-nostdin', '-y', '-i', str(source),
               '-map', '0:v:0', '-c:v', 'copy', '-an', '-movflags', '+faststart', str(target)]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=errors, creationflags=CREATE_NO_WINDOW)
        try:
            while proc.poll() is None:
                check_cancel(event)
                time.sleep(.1)
            check_cancel(event)
            if proc.returncode:
                errors.seek(0)
                raise ValueError('静音保存失败：' + errors.read().decode(errors='replace')[-900:])
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

def parse_douyin(page, item_id, referer):
    for state in states(page):
        for node in walk(state):
            identity = str(node.get('aweme_id') or node.get('awemeId') or '')
            if identity != str(item_id):
                continue
            title = node.get('desc') or f'抖音_{item_id}'
            assets = []
            for photo in node.get('images') or []:
                urls = http_urls(photo.get('url_list') or photo.get('urlList'))
                if urls:
                    assets.append(Asset('image', urls))
            if assets:
                return Work(title, assets, referer)
            video = node.get('video') or {}
            choices = []
            for rate in sorted(video.get('bit_rate') or [], key=lambda n: n.get('bit_rate', 0), reverse=True):
                choices += http_urls((rate.get('play_addr') or {}).get('url_list'))
            choices += http_urls((video.get('play_addr') or video.get('playAddr') or {}).get('url_list'))
            choices = list(dict.fromkeys(u.replace('/playwm/', '/play/') for u in choices))
            if choices:
                return Work(title, [Asset('video', choices)], referer)
    raise ValueError('抖音页面没有返回作品数据，可能需要登录、验证，或分享已失效。')

def xhs_image_urls(photo):
    """Use the file's CDN key, never H5/WB preview transforms that add a logo."""
    keys = []
    raw_urls = []
    for field in ('urlDefault', 'urlPre', 'url'):
        raw_urls += http_urls(photo.get(field))
    for info in photo.get('infoList') or []:
        if isinstance(info, dict):
            raw_urls += http_urls(info.get('url'))
    for field in ('fileId', 'file_id'):
        key = photo.get(field)
        if isinstance(key, str):
            keys.append(key.split('!', 1)[0].split('?', 1)[0].strip('/'))
    for url in raw_urls:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        path = unquote(parsed.path).split('!', 1)[0]
        if re.fullmatch(r'sns-webpic(?:-[a-z0-9]+)?\.xhscdn\.com', host):
            match = re.match(r'^/\d{8,14}/[a-zA-Z0-9]{16,}/(.+)$', path)
            if match:
                keys.append(match.group(1))
        elif host == 'ci.xiaohongshu.com' or re.fullmatch(r'sns-img(?:-[a-z0-9]+)?\.xhscdn\.com', host):
            keys.append(path.lstrip('/'))
    keys = list(dict.fromkeys(k for k in keys if k and re.fullmatch(r'[A-Za-z0-9_./-]+', k)
                             and '..' not in k.split('/')))
    return [f'https://{host}/{key}{suffix}' for suffix in ('','?imageView2/0/format/jpg')
            for key in keys for host in ('ci.xiaohongshu.com', 'sns-img-qc.xhscdn.com', 'sns-img-bd.xhscdn.com')]

def xhs_video_urls(video):
    """Rank original/casting streams ahead of known watermarked mini-app streams."""
    choices = []
    sources = [video]
    media_v2 = video.get('mediaV2')
    if isinstance(media_v2, str):
        try:
            media_v2 = json.loads(media_v2)
        except ValueError:
            media_v2 = None
    if isinstance(media_v2, dict):
        sources.append(media_v2)
    for source in sources:
        for node in walk(source):
            origin = node.get('originVideoKey') or node.get('origin_video_key')
            if isinstance(origin, str) and re.fullmatch(r'[A-Za-z0-9_./-]+', origin) and '..' not in origin.split('/'):
                choices.append('https://sns-video-bd.xhscdn.com/' + origin.lstrip('/'))
        for node in walk(source):
            for field in ('hd_screencast_stream', 'default_screencast_stream'):
                choices += http_urls(node.get(field))
    variants = [node for source in sources for node in walk(source)
                if node.get('masterUrl') and str(node.get('streamType')) not in {'259','309'}
                and 'MINI_APP' not in str(node.get('streamDesc', '')).upper()]
    def rank(node):
        preferred = str(node.get('streamType')) in {'258','301'} or 'X264_MP4' in str(node.get('streamDesc', '')).upper()
        return (node.get('width') or 0) * (node.get('height') or 0), node.get('avgBitrate') or 0, preferred
    for node in sorted(variants,key=rank,reverse=True):
        choices += http_urls(node.get('masterUrl')) + http_urls(node.get('backupUrls'))
    return list(dict.fromkeys(u.replace('http://', 'https://', 1) for u in choices))

def parse_xhs(page, note_id, referer, include_live_video=False):
    for state in states(page):
        if not isinstance(state, dict):
            continue
        detail = (state.get('note') or {}).get('noteDetailMap') or {}
        record = detail.get(note_id) or {}
        note = record.get('note') or {}
        if not note:
            for node in walk(state):
                if str(node.get('noteId', '')) == note_id and ('imageList' in node or 'video' in node):
                    note = node
                    break
        if not note:
            continue
        title = note.get('title') or note.get('desc') or f'小红书_{note_id}'
        video = note.get('video') or {}
        choices = xhs_video_urls(video)
        if choices and (note.get('type') == 'video' or not note.get('imageList')):
            return Work(title, [Asset('video', choices, '小红书原始 / 播放视频流')], referer)
        if video and note.get('type') == 'video':
            raise SourceUnavailable('此作品只提供了已知带水印的视频流，未作为无水印视频保存。请在浏览器检查，或用本地修复。')
        assets = []
        missing_kinds = set()
        for photo in note.get('imageList') or []:
            choices = xhs_image_urls(photo)
            assets.append(Asset('image', choices, '小红书原图（排除网页水印预览图）'))
            # Live photos keep their still image by default. A regular video
            # note is handled above and retains its video download.
            if include_live_video and (photo.get('livePhoto') or photo.get('live_photo')):
                live_urls = xhs_video_urls({'stream': photo.get('stream') or {}})
                if live_urls:
                    assets.append(Asset('video', live_urls, '小红书实况视频'))
                else:
                    missing_kinds.add('video')
        if assets:
            return Work(title, assets, referer, tuple(sorted(missing_kinds)))
    raise ValueError('小红书页面没有返回作品数据。请重新复制带 xsec_token 的完整分享链接；如需登录或验证，请先在浏览器完成。')

class Downloader:
    def __init__(self, event, log, progress, cookie_file='', mute=False, instagram_cookies=None):
        self.event, self.log, self.progress = event, log, progress
        self.cookie_file = cookie_file
        self.mute = mute
        self.session = requests.Session()
        from network_config import desktop_proxies
        self.session.proxies.update(desktop_proxies())
        self.session.headers['User-Agent'] = UA
        self.instagram_cookies=instagram_cookies or []
        for cookie in self.instagram_cookies:
            domain=cookie.get('domain','').lstrip('.').lower()
            if domain=='instagram.com' or domain.endswith('.instagram.com'):
                self.session.cookies.set(cookie['name'],cookie['value'],domain=cookie.get('domain',''),
                                         path=cookie.get('path','/'),secure=cookie.get('secure',True))
        if cookie_file and not self.instagram_cookies:
            import http.cookiejar
            jar = http.cookiejar.MozillaCookieJar(cookie_file)
            jar.load(ignore_discard=True, ignore_expires=False)
            self.session.cookies.update(jar)

    def page(self, url, desktop=False):
        check_cancel(self.event)
        # Platform page redirects are bounded; media uses separate GET requests.
        for _ in range(10):
            host = (urlparse(url).hostname or '').lower()
            if not any(host == d or host.endswith('.' + d) for d in PLATFORMS):
                raise ValueError('分享链接跳转到了不支持的网站。')
            with self.session.get(url, timeout=(12, 25), allow_redirects=False,
                                  headers={'User-Agent': DESKTOP_UA if desktop else UA}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers['Location'])
                    check_cancel(self.event)
                    continue
                response.raise_for_status()
                return response.url, response.content.decode('utf-8', errors='replace')
        raise ValueError('分享链接跳转次数过多。')

    def resolve(self, url):
        if social_platform(url) == 'X':
            from x_support import XBrowser
            import sys
            base = Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
            owned = not hasattr(self,'x_browser')
            browser = XBrowser(base/'x_data', self.log) if owned else self.x_browser
            try:
                items = browser.call('scan', url, False, self.event)
                return Work(items[0].title, [item.asset for item in items], items[0].url)
            finally:
                if owned:
                    browser.shutdown()
                    browser.thread.join(timeout=8)
        if social_platform(url) == 'Instagram':
            return self.resolve_instagram(url)
        final, page = self.page(url, desktop=False)
        if '/login' in urlparse(final).path:
            raise ValueError('平台返回登录页面，请在浏览器登录后导入自己的 Cookies.txt。')
        host = urlparse(final).hostname or ''
        if 'douyin.com' in host:
            match = re.search(r'/(?:video|note)/(\d+)|[?&](?:modal_id|aweme_id)=(\d+)', final)
            if not match:
                raise ValueError('请使用单个作品的分享链接，不支持主页或直播。')
            item_id = next(g for g in match.groups() if g)
            try:
                return parse_douyin(page, item_id, final)
            except ValueError:
                share = f'https://www.iesdouyin.com/share/video/{item_id}/'
                _, page = self.page(share)
                return parse_douyin(page, item_id, share)
        match = re.search(r'/(?:explore|discovery/item)/(\w+)', final)
        if not match:
            raise ValueError('未找到小红书作品编号，请复制单个作品的完整分享链接。')
        return parse_xhs(page, match.group(1), final)

    def resolve_instagram(self, url):
        if not re.search(r'/(?:[^/?#]+/)?(?:p|reels?|tv)/[^/?#]+',urlparse(url).path):
            raise SourceUnavailable('请粘贴单个 Instagram 帖子或 Reel 链接，暂不支持主页、限时动态或整页抓取。')
        import yt_dlp
        from yt_dlp.extractor.instagram import InstagramIE
        # Let the maintained extractor perform its normal access checks, but
        # capture full product metadata before its video-only result filtering.
        class ProductExtractor(InstagramIE):
            def _extract_product(self, product_info, video_id=None, get_comments=True):
                self.product = product_info
                return {'id':video_id or 'post','_type':'playlist','entries':[]}
        class Logger:
            def debug(self,*args):pass
            def warning(self,*args):pass
            def error(self,*args):pass
        options = {'quiet':True,'logger':Logger(),'socket_timeout':20,'retries':0,
                   'extractor_retries':0,'geo_bypass':False,'cachedir':False}
        from network_config import extractor_proxy
        proxy = extractor_proxy()
        if proxy:
            options['proxy'] = proxy
        with tempfile.TemporaryDirectory(prefix='qingying-ig-') as temp:
            if self.cookie_file and not self.instagram_cookies:
                import shutil
                private_cookie = Path(temp)/'cookies.txt'
                shutil.copyfile(self.cookie_file,private_cookie)
                options['cookiefile']=str(private_cookie)
            elif self.instagram_cookies:
                import http.cookiejar
                private_cookie=Path(temp)/'cookies.txt'
                jar=http.cookiejar.MozillaCookieJar(str(private_cookie))
                for cookie in self.session.cookies:
                    domain=cookie.domain.lstrip('.').lower()
                    if domain=='instagram.com' or domain.endswith('.instagram.com'):jar.set_cookie(cookie)
                jar.save(ignore_discard=True,ignore_expires=False)
                options['cookiefile']=str(private_cookie)
            check_cancel(self.event)
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    extractor=ProductExtractor(ydl)
                    extractor.extract(url)
                    product=getattr(extractor,'product',None)
            except Exception as error:
                from instagram_support import access_error
                classified=access_error(error)
                if classified:raise classified from error
                raise
            check_cancel(self.event)
        if not product:
            raise SourceUnavailable('Instagram 未返回帖子数据，请检查是否需要登录。')
        return parse_instagram_product(product,url)

    def fetch(self, asset, target_dir, stem, referer):
        if not asset.urls:
            raise SourceUnavailable('没有取得原图标识，未保存可能带水印的预览图。请重新复制完整分享链接；已有文件可用本地修复。')
        last_error = None
        for candidate in asset.urls:
            check_cancel(self.event)
            try:
                with tempfile.TemporaryDirectory(prefix='.qingying-', dir=target_dir) as temp:
                    raw = Path(temp) / 'download.bin'
                    with self.session.get(candidate, stream=True, timeout=(12, 25), headers={'Referer': referer}) as response:
                        response.raise_for_status()
                        content_type = response.headers.get('Content-Type', '').lower()
                        if 'text/html' in content_type or 'application/json' in content_type:
                            raise ValueError('服务器返回验证页，未取得媒体文件。')
                        total = int(response.headers.get('Content-Length') or 0)
                        done = 0
                        started=time.monotonic()
                        with raw.open('wb') as out:
                            for block in response.iter_content(512 * 1024):
                                check_cancel(self.event)
                                out.write(block)
                                done += len(block)
                                speed=done/1048576/max(.01,time.monotonic()-started)
                                self.progress(done / total * 100 if total else 0, f'{done / 1048576:.1f} MB · {speed:.1f} MB/s')
                    if not done or (total and done != total):
                        raise ValueError('下载数据不完整，请重试。')
                    if asset.kind == 'image':
                        with Image.open(raw) as img:
                            fmt = img.format
                            img.verify()
                        ext = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'GIF': '.gif', 'AVIF':'.avif'}.get(fmt)
                        if ext is None:
                            raise ValueError(f'不支持的图片格式：{fmt}')
                    else:
                        import cv2
                        cap = cv2.VideoCapture(str(raw))
                        ok, _ = cap.read()
                        cap.release()
                        if not ok:
                            raise ValueError('下载内容不能解码为视频，未保存伪视频文件。')
                        ext = '.mp4'
                    if self.mute and asset.kind == 'video':
                        self.log('正在移除音轨，视频画质保持不变…')
                        muted = Path(temp) / 'muted.mp4'
                        mute_video(raw, muted, self.event)
                        raw = muted
                    check_cancel(self.event)
                    target = unique_path(target_dir, stem, ext)
                    raw.rename(target)
                    return target
            except Cancelled:
                raise
            except Exception as error:
                last_error = error
        if asset.source.startswith('小红书原图'):
            raise SourceUnavailable(f'原图下载失败，未退回带水印预览图。请稍后重试或检查链接。详情：{last_error}')
        raise ValueError(f'所有媒体地址均下载失败：{last_error}')

    def fetch_many(self, assets, folder, stem, referer, workers=3):
        """Bounded media transfers with private reusable sessions per worker."""
        from concurrent.futures import ThreadPoolExecutor,as_completed
        assets=list(assets)
        if not assets:return [],[]
        workers=max(1,min(workers,len(assets)))
        fractions=[0.0]*len(assets);guard=threading.Lock();local=threading.local();sessions=[]
        headers=dict(self.session.headers);cookies=self.session.cookies.copy()
        proxies=dict(self.session.proxies);trust_env=self.session.trust_env
        def report(index,value,message):
            with guard:
                fractions[index]=max(fractions[index],min(100,value))
                self.progress(sum(fractions)/len(assets),f'文件 {index+1}/{len(assets)} · {message}')
        def transfer(index,asset):
            check_cancel(self.event)
            if not hasattr(local,'downloader'):
                child=Downloader(self.event,self.log,lambda *args:None,mute=self.mute)
                child.session.headers.update(headers);child.session.cookies.update(cookies)
                child.session.proxies.update(proxies);child.session.trust_env=trust_env
                local.downloader=child
                with guard:sessions.append(child.session)
            child=local.downloader
            child.progress=lambda value,message:report(index,value,message)
            output=child.fetch(asset,folder,f'{stem}_{index+1:02}',referer)
            report(index,100,'已保存')
            return output
        results={};errors={}
        try:
            with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='qingying-media') as pool:
                futures={pool.submit(transfer,i,asset):i for i,asset in enumerate(assets)}
                for future in as_completed(futures):
                    index=futures[future]
                    try:results[index]=future.result()
                    except Cancelled:
                        for pending in futures:pending.cancel()
                    except Exception as error:errors[index]=str(error)
            check_cancel(self.event)
            return [results[i] for i in sorted(results)],[f'第 {i+1} 个：{errors[i]}' for i in sorted(errors)]
        finally:
            for session in sessions:session.close()

    def fallback_video(self, url, folder):
        import yt_dlp
        import imageio_ffmpeg
        def hook(data):
            check_cancel(self.event)
            total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
            done = data.get('downloaded_bytes', 0)
            self.progress(done / total * 100 if total else 0, '备用解析器下载中')
        class Logger:
            def debug(self, message): pass
            def warning(self, message): pass
            def error(self, message): pass
        with tempfile.TemporaryDirectory(prefix='.qingying-', dir=folder) as temp:
            options = {'quiet': True, 'no_warnings': True, 'logger': Logger(),
                       'noplaylist': True, 'socket_timeout': 20, 'retries': 1, 'concurrent_fragment_downloads':3,
                       'extractor_retries':1,'geo_bypass':False,'cachedir':False,
                       'format': 'bv*+ba/bv*/b',
                       'merge_output_format':'mp4', 'outtmpl': str(Path(temp) / 'media.%(ext)s'),
                       'progress_hooks': [hook], 'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe()}
            if self.cookie_file:
                # Work on a private copy: yt-dlp must not rewrite the user's cookie file.
                import shutil
                private_cookie = Path(temp) / 'cookies.txt'
                shutil.copyfile(self.cookie_file, private_cookie)
                options['cookiefile'] = str(private_cookie)
            from network_config import extractor_proxy
            proxy=extractor_proxy()
            if proxy:options['proxy']=proxy
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
            check_cancel(self.event)
            files = [p for p in Path(temp).glob('media.*') if p.suffix not in {'.part', '.ytdl'}]
            if not files:
                raise ValueError('备用解析器未生成媒体文件。')
            result = []
            for path in files:
                verified=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(path),
                                         '-frames:v','1','-f','null','-'],capture_output=True,
                                        creationflags=CREATE_NO_WINDOW,timeout=40)
                if verified.returncode:
                    raise ValueError('备用解析器下载的文件无法解码。')
                if self.mute:
                    self.log('正在移除音轨，视频画质保持不变…')
                    muted = Path(temp) / 'muted.mp4'
                    mute_video(path, muted, self.event)
                    path = muted
                out = unique_path(folder, info.get('title') or '作品', path.suffix)
                path.rename(out)
                result.append(out)
            return result

    def download(self, url, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.log('正在解析分享链接…')
        platform=social_platform(url)
        if platform:
            self.log(f'{platform}：只下载所选作品，不处理主页或整页内容。')
        if platform == 'Facebook':
            try:
                result=self.fallback_video(url,folder)
                for path in result:self.log('已保存：'+str(path))
                return result
            except Cancelled:
                raise
            except Exception as error:
                check_cancel(self.event)
                raise ValueError('Facebook 下载失败。请检查链接是否有效及网络；需登录时，在浏览器完成登录后导入自己的 Cookies.txt。\n详情：'+str(error)) from error
        try:
            work = self.resolve(url)
        except SourceUnavailable:
            raise
        except Cancelled:
            raise
        except Exception as error:
            if platform == 'X':
                raise ValueError('X 解析失败：'+str(error)) from error
            if platform == 'Instagram':
                from instagram_support import InstagramAccessError
                if isinstance(error,InstagramAccessError):raise
                raise ValueError('Instagram 解析失败。请检查帖子是否可访问及网络；需登录时，在浏览器完成登录后导入自己的 Cookies.txt。\n详情：'+str(error)) from error
            host = urlparse(url).hostname or ''
            if hasattr(self, 'resolve_xhs') and (host in {'xhslink.com', 'www.xhslink.com', 'xiaohongshu.com', 'www.xiaohongshu.com'}):
                self.log('小红书网页解析未成功，正在使用清影内置浏览器读取作品。')
                from collector import LoginRequired
                try:
                    work, _, cookies = self.resolve_xhs(url)
                except LoginRequired as login_error:
                    raise SourceUnavailable('请在清影小红书内置浏览器完成登录或验证，然后重试链接下载。') from login_error
                for cookie in cookies:
                    domain = cookie.get('domain', '').lstrip('.').lower()
                    if domain in {'xiaohongshu.com', 'www.xiaohongshu.com'}:
                        self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'],
                                                 path=cookie.get('path', '/'), secure=cookie.get('secure', True))
            else:
                self.log(str(error))
                self.log('尝试备用视频解析器…')
                try:
                    return self.fallback_video(url, folder)
                except Exception as fallback:
                    check_cancel(self.event)
                    raise ValueError('解析失败。请检查作品是否公开、链接是否完整；需登录时可导入自己导出的 Cookies.txt 后重试。平台验证或失效链接无法自动处理。\n详情：' + str(fallback)) from fallback
        self.log(f'作品：{work.title[:70]}；共 {len(work.assets)} 个文件')
        self.log('正在并发保存原文件，最多同时下载 3 个…')
        results,errors=self.fetch_many(work.assets,folder,work.title,work.referer)
        if errors:
            raise ValueError(f'已保存 {len(results)}/{len(work.assets)} 个文件，部分失败；成功文件已保留。\n' + '\n'.join(errors))
        return results

def load_preview(path, fraction=0):
    path = Path(path)
    if path.suffix.lower() in IMAGE_EXTS:
        with Image.open(path) as img:
            if getattr(img, 'n_frames', 1) > 1:
                raise ValueError('本地修复暂不支持动图，请转成视频后处理。')
            return ImageOps.exif_transpose(img).convert('RGBA'), None
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        frames, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS)
        if fraction and frames > 1:
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(frames - 1, int(frames * fraction)))
        ok, frame = cap.read()
        if not ok:
            raise ValueError('无法打开该文件。图片支持 JPG/PNG/WebP；视频建议 MP4/MOV。')
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), (frames / fps if fps else 0)
    finally:
        cap.release()

def image_restore(image, boxes):
    import cv2
    import numpy as np
    if not boxes:return image.copy()
    alpha = image.getchannel('A') if image.mode == 'RGBA' else None
    pixels = np.array(image.convert('RGB'))
    h,w=pixels.shape[:2]
    left=max(0,min(int(b[0]) for b in boxes)-24);top=max(0,min(int(b[1]) for b in boxes)-24)
    right=min(w,max(int(b[2]) for b in boxes)+24);bottom=min(h,max(int(b[3]) for b in boxes)+24)
    mask = np.zeros((bottom-top,right-left), np.uint8)
    for x1, y1, x2, y2 in boxes:
        mask[max(0,y1-top):min(bottom-top,y2-top),max(0,x1-left):min(right-left,x2-left)] = 255
    pixels[top:bottom,left:right]=cv2.inpaint(pixels[top:bottom,left:right], mask, 3, cv2.INPAINT_TELEA)
    result = Image.fromarray(pixels)
    if alpha is not None:
        result.putalpha(alpha)
    return result

@lru_cache(maxsize=1)
def hardware_encoding_available():
    import imageio_ffmpeg
    try:
        command=[imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i','color=s=320x240:r=24',
                 '-frames:v','1','-c:v','h264_nvenc','-preset','p4','-cq','18','-b:v','0','-f','null','-']
        return subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                              timeout=8,creationflags=CREATE_NO_WINDOW).returncode==0
    except (OSError,subprocess.TimeoutExpired):return False

def encode_video(command,event,progress,duration,label,errors):
    """Run FFmpeg away from Tk; stop the process promptly on cancellation."""
    errors.seek(0);errors.truncate()
    proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors,creationflags=CREATE_NO_WINDOW)
    def reader():
        for raw in proc.stdout:
            line=raw.decode(errors='replace').strip()
            if line.startswith('out_time_us='):
                try:
                    seconds=int(line.split('=',1)[1])/1000000
                    progress(min(99,seconds/duration*100) if duration else 0,f'{label} · 已处理 {seconds:.1f} 秒')
                except ValueError:pass
    thread=threading.Thread(target=reader,daemon=True);thread.start()
    try:
        while proc.poll() is None:check_cancel(event);time.sleep(.1)
        thread.join(timeout=5)
        return proc.returncode
    finally:
        if proc.poll() is None:proc.kill()
        proc.wait();thread.join(timeout=5);proc.stdout.close()

def restore(path, folder, boxes, event, progress):
    path, folder = Path(path), Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    preview, duration = load_preview(path)
    w, h = preview.size
    boxes = [(max(0, min(w, int(a))), max(0, min(h, int(b))),
              max(0, min(w, int(c))), max(0, min(h, int(d)))) for a,b,c,d in boxes]
    boxes = [b for b in boxes if b[2]-b[0] >= 2 and b[3]-b[1] >= 2]
    if not boxes:
        raise ValueError('请先在预览中拖动框选水印区域。')
    check_cancel(event)
    target = unique_path(folder, path.stem + '_去水印', '.png' if duration is None else '.mp4')
    with tempfile.TemporaryDirectory(prefix='.qingying-', dir=folder) as temp:
        pending = Path(temp) / target.name
        if duration is None:
            image_restore(preview, boxes).save(pending, 'PNG')
        else:
            import imageio_ffmpeg
            # delogo interpolates spatially. A one-pixel outer border is required.
            filters = []
            for a,b,c,d in boxes:
                a,b,c,d = max(1,a),max(1,b),min(w-1,c),min(h-1,d)
                if c-a < 2 or d-b < 2:
                    raise ValueError('水印区域太贴近边缘或过小，请向内调整选框。')
                filters.append(f'delogo=x={a}:y={b}:w={c-a}:h={d-b}')
            filters.append('pad=ceil(iw/2)*2:ceil(ih/2)*2')
            encoders=[('快速编码',['-c:v','libx264','-crf','18','-preset','veryfast'])]
            if w>=128 and h>=128 and hardware_encoding_available():
                encoders.insert(0,('显卡加速',['-c:v','h264_nvenc','-preset','p4','-cq','18','-b:v','0']))
            with (Path(temp) / 'ffmpeg.log').open('w+b') as errors:
                for label,options in encoders:
                    check_cancel(event);progress(0,label+'中…')
                    cmd=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-nostdin','-y','-i',str(path),
                         '-vf',','.join(filters),'-map','0:v:0','-map','0:a?',*options,
                         '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',
                         '-progress','pipe:1','-nostats',str(pending)]
                    if encode_video(cmd,event,progress,duration,label,errors)==0:break
                else:
                    errors.seek(0)
                    raise ValueError('视频处理失败：'+errors.read().decode(errors='replace')[-1600:])
        check_cancel(event)
        pending.rename(target)
    progress(100, '处理完成')
    return target

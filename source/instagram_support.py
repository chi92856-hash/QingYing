"""Instagram access failures, resumable batches and a user-owned login window."""
from dataclasses import dataclass,field
from email.utils import parsedate_to_datetime
import math,time
from common import Cancelled

class InstagramAccessError(ValueError):
    retry_at=0

class InstagramRateLimited(InstagramAccessError):
    def __init__(self,retry_at=None):
        self.retry_at=retry_at or time.time()+300
        super().__init__('Instagram 暂时限制请求（HTTP 429）。已停止后续 Instagram 请求；稍后再试，需要登录时请使用“Instagram 登录”或自己的 Cookies.txt。')

def access_error(error):
    chain=[];seen=set();current=error
    while current is not None and id(current) not in seen:
        seen.add(id(current));chain.append(current)
        current=getattr(current,'cause',None) or current.__cause__ or current.__context__
    for item in chain:
        response=getattr(item,'response',None)
        status=getattr(item,'status',None) or getattr(response,'status',None) or getattr(response,'status_code',None)
        if status==429 or 'HTTP Error 429' in str(item) or 'HTTP 429' in str(item):
            raw=(getattr(response,'headers',{}) or {}).get('Retry-After','')
            delay=300
            try:
                value=float(raw)
                if math.isfinite(value) and value>=0:delay=value
            except (ValueError,TypeError):
                try:delay=max(0,parsedate_to_datetime(raw).timestamp()-time.time())
                except (ValueError,TypeError,AttributeError,OverflowError):pass
            return InstagramRateLimited(time.time()+max(1,delay))
    message=' '.join(str(item).lower() for item in chain)
    if 'curl: (28)' in message or 'connection timed out' in message:
        return InstagramAccessError('Instagram 网络连接超时。已保留待下载链接并暂停本批 Instagram 请求，请确认内置浏览器能打开该作品及系统代理正常，再点击继续下载。')
    if any(term in message for term in ('login required','log in to','login_required','challenge_required','checkpoint_required','cookies are no longer valid')):
        return InstagramAccessError('Instagram 要求登录或验证。请点击“Instagram 登录”，在清影内置浏览器手动完成后，再继续待下载作品。')
    return None

@dataclass
class BatchResult:
    files:int=0
    failed:int=0
    successful:list=field(default_factory=list)
    pending:list=field(default_factory=list)
    blocked:object=None
    cancelled:bool=False

def download_batch(downloader,urls,folder,existing_pending=(),blocked=None):
    from core import social_platform,check_cancel
    result=BatchResult(blocked=blocked)
    for index,url in enumerate(urls,1):
        try:
            check_cancel(downloader.event)
            if result.blocked and social_platform(url)=='Instagram':
                result.pending.append(url);continue
            downloader.log(f'—— 作品 {index}/{len(urls)} ——')
            files=downloader.download(url,folder)
            result.files+=len(files);result.successful.append(url)
            for path in files:downloader.log('保存成功：'+path.name)
        except Cancelled:
            result.cancelled=True
            result.pending.extend(urls[index-1:])
            break
        except InstagramAccessError as error:
            result.blocked=error;result.pending.append(url);downloader.log(str(error))
        except Exception as error:
            result.failed+=1;downloader.log(str(error))
    result.pending=list(dict.fromkeys([url for url in existing_pending if url not in result.successful]+result.pending))
    return result

def create_browser(data_dir,log):
    from collector import BrowserWorker
    class InstagramBrowser(BrowserWorker):
        def _login(self):
            self.embedded.call('show')
            return '已打开 Instagram 内置浏览器。请完成登录或验证，再回清影下载。登录状态会保留。'
        def _cookies(self):
            try:
                self._ensure()
                cookies=self.context.cookies(['https://www.instagram.com/'])
            except Exception as error:
                raise InstagramAccessError(f'无法读取 Instagram 内置浏览器的登录状态。请重新打开“Instagram 登录”后重试。{error}') from error
            return cookies if any(c.get('name')=='sessionid' and c.get('value') for c in cookies) else []
    return InstagramBrowser(data_dir,log,embedded='instagram')

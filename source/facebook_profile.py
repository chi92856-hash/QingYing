"""User-started archiving of a public Facebook profile's own media."""
import html
import http.cookiejar
import json
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse,parse_qs,urlencode,urljoin
from core import Asset,Downloader,Cancelled,check_cancel,safe_name,walk
from facebook_browser import EmbeddedFacebook,facebook_url
from facebook_history import FacebookHistory

STATE_JS=r"""(() => ({url:location.href,title:document.title,
 heading:(document.querySelector('h1')||{}).innerText||'',
 login:!!document.querySelector('input[type="password"]'),
 blocked:/checkpoint|captcha|two_step_verification/.test(location.pathname),
 text:(document.querySelector('[role="main"]')||document.body).innerText.slice(0,3000),
 loading:!!document.querySelector('[role="status"]'),
 links:[...document.querySelectorAll('[role="main"] a[href],main a[href]')].filter(a=>!a.closest('[aria-label^="评论者"]')).map(a=>({url:a.href,title:(a.innerText||a.getAttribute('aria-label')||'').slice(0,100),isReel:/\/reel\//.test(a.href)||!!a.closest('[role="article"]')?.querySelector('a[href*="/reel/"]')}))}))()"""


def profile_id(url):
    p=urlparse(url)
    if not facebook_url(url):return None
    identifier=(parse_qs(p.query).get('id') or [''])[0]
    if identifier.isdigit():return identifier
    m=re.search(r'/people/[^/]+/(\d+)',p.path)
    if m:return m.group(1)
    path=p.path.strip('/')
    return path if path.isdigit() else None


def profile_key(url):
    if not facebook_url(url):return None
    identifier=profile_id(url)
    if identifier:return 'id:'+identifier
    path=urlparse(url).path.strip('/').casefold()
    reserved={'profile.php','photo.php','photo','watch','reel','reels','videos','login','friends','groups','people','share','permalink.php','home.php'}
    if path and '/' not in path and path not in reserved:return 'name:'+path
    return None


def identify_profile(url,scripts):
    """Match the viewed profile, never the viewer or a commenter in page data."""
    target=profile_key(url);target_id=profile_id(url)
    matches={};aliases={}
    if target is None:return None,set()
    for script in scripts:
        try:data=json.loads(script)
        except (ValueError,TypeError):continue
        for node in walk(data):
            if node.get('__typename') not in ('User','Page'):continue
            identifier=str(node.get('id') or '')
            if not identifier.isdigit():continue
            urls=[node.get(k) for k in ('url','profile_url') if isinstance(node.get(k),str)]
            keys={profile_key(u) for u in urls}-{None}
            if (target_id and identifier==target_id) or target in keys:
                matches[identifier]=True;aliases.setdefault(identifier,set()).update(keys)
    if len(matches)>1:return None,set()
    identifier=next(iter(matches),None) or target_id
    if not identifier:return None,set()
    return identifier,aliases.get(identifier,set())|{target,'id:'+identifier}


def media_item(url,title=''):
    if not facebook_url(url):return None
    p=urlparse(url);q=parse_qs(p.query)
    # Comment attachments and tagged content are outside the requested scope.
    if 'comment_id' in q or 'reply_comment_id' in q:return None
    identifier=(q.get('fbid') or [''])[0]
    if p.path in ('/photo/','/photo.php') and identifier.isdigit():
        return dict(id='photo_'+identifier,kind='image',url='https://www.facebook.com/photo.php?'+urlencode({'fbid':identifier}),title=title)
    m=re.search(r'/(?:reel|videos)/(?:[^/]+/)?(\d+)(?:/|$)',p.path)
    identifier=m.group(1) if m else (q.get('v') or [''])[0]
    if identifier.isdigit():
        return dict(id='video_'+identifier,kind='video',url='https://www.facebook.com/watch/?v='+identifier,title=title)
    return None


TYPE_LABELS={'photos':'照片','albums':'相册','videos':'视频','reels':'Reels'}
SCAN_LIMIT=500


def selected_categories(categories):
    selected=list(TYPE_LABELS) if categories is None else [key for key in TYPE_LABELS if key in categories]
    if not selected:raise ValueError('请至少开启一种下载类型。')
    return selected


def album_url(url):
    if not facebook_url(url) or urlparse(url).path.rstrip('/')!='/media/set':return None
    value=(parse_qs(urlparse(url).query).get('set') or [''])[0]
    if not re.fullmatch(r'a\.\d+',value):return None
    return 'https://www.facebook.com/media/set/?'+urlencode({'set':value,'type':'3'})


def photo_sources(page_html,identifier,dom_images):
    candidates=[]
    for script in re.findall(r'<script\b[^>]*type="application/json"[^>]*>(.*?)</script>',page_html,re.S):
        try:data=json.loads(script)
        except ValueError:continue
        for node in walk(data):
            if node.get('__typename')=='Photo' and str(node.get('id'))==identifier:
                # Only image variants belonging to this exact photo, never
                # comment avatars, cover thumbnails or suggested media.
                for key in ('image','photo_image','image_full','viewer_image'):
                    image=node.get(key)
                    if isinstance(image,dict) and image.get('uri'):
                        candidates.append((int(image.get('width') or 0)*int(image.get('height') or 0),image['uri']))
    for image in dom_images:
        if image.get('url') and image.get('width',0)>200:
            candidates.append((image.get('width',0)*image.get('height',0),image['url']))
    urls=[]
    for _,url in sorted(candidates,key=lambda p:p[0],reverse=True):
        parsed=urlparse(html.unescape(url))
        if parsed.scheme=='https' and (parsed.hostname or '').endswith('.fbcdn.net') and url not in urls:urls.append(url)
    return urls


class FacebookArchive:
    def __init__(self,data_dir,log,progress):
        self.data_dir=Path(data_dir)
        self.browser=EmbeddedFacebook(self.data_dir/'browser')
        self.history=FacebookHistory(self.data_dir/'history.sqlite3')
        self.log,self.progress=log,progress
        self.profile_aliases={}

    def identify(self,state,cancel):
        for _ in range(10):
            scripts=self.browser.evaluate("[...document.querySelectorAll('script[type=\"application/json\"]')].map(x=>x.textContent)")
            identifier,aliases=identify_profile(state['url'],scripts if isinstance(scripts,list) else [])
            if identifier:
                self.profile_aliases[identifier]=aliases
                return identifier
            self.wait(cancel,.5)
            state=self.state(cancel)
        raise ValueError('未能确认当前博主的主页资料。请检查内置浏览器是否仍在目标主页、页面是否已加载完成，或是否要求登录验证；不会使用其他账号的编号。')

    def is_owner(self,url,profile):
        return profile_id(url)==profile or profile_key(url) in self.profile_aliases.get(profile,set())

    def wait(self,cancel,seconds=2):
        if cancel.wait(seconds):check_cancel(cancel)

    def state(self,cancel):
        for _ in range(12):
            check_cancel(cancel)
            state=self.browser.evaluate(STATE_JS)
            if isinstance(state,dict):return state
            self.wait(cancel,.5)
        raise ValueError('Facebook 正在切换页面，暂时无法读取作品。记录已保留，请稍后继续。')

    def navigate(self,url,cancel):
        self.browser.goto(url)
        self.wait(cancel,2)
        for _ in range(20):
            check_cancel(cancel)
            state=self.state(cancel)
            if state.get('blocked'):raise ValueError('Facebook 要求验证。请在清影内置浏览器手动完成后继续，任务记录已保留。')
            if state.get('login'):raise ValueError('请先在清影内置浏览器登录 Facebook。登录状态会自动保留；完成后再点击“扫描并全部保存”。')
            if state.get('links') or state.get('text'):return state
            self.wait(cancel,1)
        raise ValueError('Facebook 页面未正常加载。请检查内置浏览器，已有进度已保留。')

    def open_login(self):
        self.browser.ensure();self.browser.call('show')
        return '清影内置浏览器已打开，登录状态自动保留。首次使用请手动登录 Facebook。'

    def scroll_links(self,cancel,label,collect,count):
        stable=0;last=None;state={}
        while stable<5:
            check_cancel(cancel);state=self.state(cancel)
            if state.get('login') or state.get('blocked'):raise ValueError('扫描遇到登录或验证提示，请在内置浏览器处理后继续。')
            if collect(state.get('links',[])) is True:return False
            keys=[]
            for link in state.get('links',[]):
                item=media_item(link['url'])
                key=item['id'] if item else album_url(link['url'])
                if key and key not in keys:keys.append(key)
            signature=(count(),tuple(keys[-4:]))
            stable=stable+1 if signature==last else 0;last=signature
            self.progress(0,f'正在扫描 {label} · 已发现 {count()} 项')
            self.browser.evaluate('window.scrollTo(0,document.documentElement.scrollHeight);true')
            self.wait(cancel,1.5)
        return state.get('loading',False)

    def click_tab(self,label,cancel):
        for _ in range(6):
            clicked=self.browser.evaluate("""(() => {let a=[...document.querySelectorAll('[role="tab"]')].find(x=>x.getClientRects().length&&x.innerText.trim()===%s);if(!a)return false;if(a.getAttribute('aria-selected')==='true')return true;a.scrollIntoView({block:'nearest'});let r=a.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()""" % json.dumps(label))
            if isinstance(clicked,dict):self.browser.call('click',clicked)
            if clicked:
                self.wait(cancel,2)
                selected=self.browser.evaluate("""[...document.querySelectorAll('[role="tab"]')].some(x=>x.getClientRects().length&&x.innerText.trim()===%s&&x.getAttribute('aria-selected')==='true')""" % json.dumps(label))
                if selected:return True
            self.wait(cancel,1)
        return False

    def scan(self,url,folder,cancel,sections=None,categories=None,scan_limit=SCAN_LIMIT):
        scan_limit=int(scan_limit)
        if scan_limit<1:raise ValueError('扫描上限需大于0。')
        self.last_scan_limited=False
        self.last_scan_count=0
        self.log(f'本轮最多扫描 {scan_limit} 个不重复媒体项，扫描上限与下载数量分别计算。')
        known_id=profile_id(url)
        self.log('已展开主页链接；路径 '+urlparse(url).path+'；主页编号 '+str(known_id or '待浏览器确认'))
        if known_id:url='https://www.facebook.com/profile.php?id='+known_id
        state=self.navigate(url,cancel)
        identifier=self.identify(state,cancel)
        self.log('已识别 Facebook 主页：'+(state.get('heading') or state.get('title') or identifier))
        base='https://www.facebook.com/profile.php?id='+identifier;found=set();scanned=set();incomplete=[]
        choices=sections if sections is not None else [(key,TYPE_LABELS[key]) for key in selected_categories(categories)]
        for section,label in choices:
            if len(scanned)>=scan_limit:break
            category='videos' if section=='timeline' else section
            check_cancel(cancel)
            self.navigate(base,cancel)
            self.browser.evaluate('window.scrollTo(0,0);true')
            self.wait(cancel,2)
            if category!='videos':
                target='照片' if category=='albums' else label
                if not self.click_tab(target,cancel):
                    incomplete.append(label+'入口未显示');continue
            self.log('正在扫描：'+label+'；发现后即时写入续传记录。')
            seen_category=set()
            def collect(links):
                for link in links:
                    item=media_item(link['url'],link.get('title',''))
                    if not item:continue
                    if category in ('photos','albums') and item['kind']!='image':continue
                    if category in ('videos','reels') and item['kind']!='video':continue
                    if category=='videos' and (link.get('isReel') or '/reel/' in urlparse(link['url']).path):continue
                    if item['id'] in seen_category:continue
                    seen_category.add(item['id'])
                    if item['id'] not in scanned and len(scanned)>=scan_limit:return True
                    scanned.add(item['id'])
                    if self.history.completed(identifier,folder,item['id']):
                        if len(scanned)>=scan_limit:return True
                        continue
                    self.history.discover(identifier,folder,item,category=category);found.add(item['id'])
                    if len(scanned)>=scan_limit:return True
                return False
            if category=='albums':
                if not self.click_tab('相册',cancel):incomplete.append('相册入口未显示');continue
                albums=set()
                def collect_albums(links):
                    for link in links:
                        value=album_url(link['url'])
                        if value:albums.add(value)
                        if len(albums)>=scan_limit:return True
                    return False
                self.scroll_links(cancel,'相册目录',collect_albums,lambda:len(albums))
                for index,album in enumerate(sorted(albums),1):
                    if len(scanned)>=scan_limit:break
                    self.navigate(album,cancel)
                    if self.scroll_links(cancel,f'相册 {index}/{len(albums)}',collect,lambda:len(scanned)):
                        incomplete.append(f'相册 {index} 仍有加载提示')
            elif self.scroll_links(cancel,label,collect,lambda:len(scanned)):
                incomplete.append(label+'仍有加载提示')
        self.last_scanned_ids=set(scanned)
        self.last_scan_count=len(scanned)
        self.last_scan_limited=len(scanned)>=scan_limit
        if self.last_scan_limited:
            self.log(f'已达到 {scan_limit} 项扫描上限，停止继续翻页，直接进入下载。')
            self.progress(0,f'已扫描 {len(scanned)}/{scan_limit} 项，开始下载')
        return identifier,found,incomplete

    def resolve_photo(self,item,profile,cancel):
        self.navigate(item['url'],cancel)
        for _ in range(12):
            data=self.browser.evaluate("""(() => {let dialog=document.querySelector('[role="dialog"]')||document.body;let main=dialog.querySelector('[role="main"],main');return {public:[...dialog.querySelectorAll('img,[role="img"]')].some(x=>/分享对象.*公开|分享對象.*公開|Shared with Public|Shared with: Public/i.test(x.alt||x.getAttribute('aria-label')||x.getAttribute('title')||'')),owners:[...dialog.querySelectorAll('[role="complementary"] a[href],aside a[href],h2 a[href],h3 a[href]')].map(x=>x.href),html:document.documentElement.outerHTML,images:main?[...main.querySelectorAll('img')].map(x=>({url:x.currentSrc||x.src,width:x.naturalWidth,height:x.naturalHeight})):[],labels:[...dialog.querySelectorAll('img,[role="img"]')].map(x=>x.alt||x.getAttribute('aria-label')||x.getAttribute('title')||'').filter(x=>/public|分享|公开|公開/i.test(x)).slice(0,10)}})()""")
            if not isinstance(data,dict):self.wait(cancel,.5);continue
            if data['public'] and data['owners'] and data['images']:break
            self.wait(cancel,1)
        if not isinstance(data,dict) or not data['public']:raise ValueError('无法确认此照片为公开作品，已跳过并保留记录。')
        if not any(self.is_owner(u,profile) for u in data['owners']):raise ValueError('此照片作者与目标博主不一致或未能确认，已跳过。')
        urls=photo_sources(data['html'],item['id'].split('_',1)[1],data['images'])
        if not urls:raise ValueError('没有获取可下载的照片源文件，未用缩略图替代。')
        return Asset('image',urls,'Facebook 公开照片')

    def save_item(self,item,profile,folder,cancel):
        if item['kind']=='image':asset=self.resolve_photo(item,profile,cancel)
        else:
            self.navigate(item['url'],cancel)
            proof=self.browser.evaluate("""(() => ({public:[...document.querySelectorAll('img,[role="img"]')].some(x=>/分享对象.*公开|Shared with Public/i.test(x.alt||x.getAttribute('aria-label')||x.getAttribute('title')||'')),owners:[...document.querySelectorAll('h2 a[href],h3 a[href]')].map(x=>x.href)}))()""")
            if not isinstance(proof,dict) or not proof['public'] or not any(self.is_owner(u,profile) for u in proof['owners']):
                raise ValueError('未能确认视频为目标博主的公开作品，已保留待重试。')
        cookies=self.browser.call('cookies')
        with tempfile.TemporaryDirectory(prefix='qingying-fb-') as temp:
            cookiefile=Path(temp)/'cookies.txt'
            jar=http.cookiejar.MozillaCookieJar(str(cookiefile))
            import requests
            session=requests.Session()
            for c in cookies:session.cookies.set(c['name'],c['value'],domain=c['domain'],path=c['path'],secure=c['secure'])
            for c in session.cookies:jar.set_cookie(c)
            jar.save(ignore_discard=True,ignore_expires=True);session.close()
            downloader=Downloader(cancel,self.log,lambda *_:None,cookie_file=str(cookiefile),mute=False)
            try:
                if item['kind']=='image':files=[downloader.fetch(asset,folder,item['id'],item['url'])]
                else:files=downloader.fallback_video(item['url'],folder)
            finally:downloader.session.close()
        return files

    def save_with_budget(self,item,profile,folder,cancel,budget):
        committed=[]
        try:
            with tempfile.TemporaryDirectory(prefix='.qingying-limit-',dir=folder) as temp:
                staging=Path(temp).resolve()
                files=self.save_item(item,profile,staging,cancel)
                check_cancel(cancel)
                if not files or len(files)>budget.remaining(item['kind']):
                    raise ValueError('作品文件数量超过该类剩余名额，未保存，已留待下次。')
                for path in files:
                    path=Path(path)
                    if not path.resolve().is_relative_to(staging):raise ValueError('临时媒体路径无效。')
                    target=folder/path.name
                    if target.exists():
                        from core import unique_path
                        target=unique_path(folder,path.stem,path.suffix)
                    path.rename(target);committed.append(target)
                self.history.mark(profile,folder,item['id'],committed)
                budget.record(item['kind'],len(committed))
            return committed
        except BaseException:
            for path in committed:
                if path.parent==folder:path.unlink(missing_ok=True)
            raise

    def run(self,url,folder,cancel,categories=None,photo_limit=200,video_limit=20,scan_limit=SCAN_LIMIT,item_limit=200):
        categories=selected_categories(categories)
        from facebook_limits import TotalBudget, parse_item_limit
        active=[]
        if set(categories)&{'photos','albums'}:active.append('image')
        if set(categories)&{'videos','reels'}:active.append('video')
        scan_limit=parse_item_limit(item_limit)
        budget=TotalBudget(scan_limit,active)
        if not facebook_url(url):raise ValueError('请输入 Facebook 主页 HTTPS 链接。')
        folder=Path(folder).expanduser().resolve();folder.mkdir(parents=True,exist_ok=True)
        self.log('本次类型：'+' / '.join(TYPE_LABELS[key] for key in categories))
        self.log(f'本次扫描并下载上限 {scan_limit} 项，照片和视频合计；重复跳过。')
        profile,found,incomplete=self.scan(url,folder,cancel,categories=categories,scan_limit=scan_limit)
        pending=[item for item in self.history.pending(profile,folder,categories=categories)
                 if item['id'] in self.last_scanned_ids]
        self.log(f'本次扫描 {getattr(self,"last_scan_count",len(found))} 项，其中未完成 {len(found)} 项；本批待保存 {len(pending)} 个。')
        saved=failed=0
        for index,item in enumerate(pending,1):
            check_cancel(cancel)
            if budget.full():break
            if self.history.completed(profile,folder,item['id']) or budget.remaining(item['kind'])==0:continue
            self.progress((index-1)/max(1,len(pending))*100,budget.summary()+f' · 失败 {failed}')
            try:
                files=self.save_with_budget(item,profile,folder,cancel,budget)
                saved+=len(files);self.log('保存成功：'+item['id']+' · '+budget.summary())
            except Cancelled:raise
            except Exception as e:
                failed+=1;self.history.mark(profile,folder,item['id'],error=str(e));self.log(item['id']+'：'+str(e))
                message=str(e).lower()
                if any(s in message for s in ('429','验证码','要求验证','login','登录','连接超时')):
                    raise ValueError('访问已暂停，剩余任务已保留。'+str(e)) from e
        remaining=self.history.pending(profile,folder,categories)
        limited=any(budget.remaining(item['kind'])==0 for item in remaining)
        summary='本轮：'+budget.summary()+f'；{failed} 个媒体待重试。'
        self.progress(100,summary)
        if limited:summary+='已达到本次数量上限，剩余记录留待下次启动。'
        if getattr(self,'last_scan_limited',False):summary+=f'扫描按 {scan_limit} 项上限结束。'
        return summary+('扫描未确认到底：'+'；'.join(incomplete) if incomplete else '扫描范围以平台当前可加载内容为准。')


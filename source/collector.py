"""Small, user-driven XHS batches with persistent login and completed-note history."""
from __future__ import annotations
from dataclasses import dataclass,field
from pathlib import Path
from concurrent.futures import Future
from contextlib import contextmanager
from common import saved_files_exist
from urllib.parse import urlparse,parse_qs,urlencode
import json,queue,re,sqlite3,threading,time,tempfile,unicodedata
import requests
from core import (Work,Downloader,Cancelled,SourceUnavailable,check_cancel,states,walk,
                  parse_xhs,unique_path)

class LoginRequired(ValueError):pass


def get_collector(app):
    service = getattr(app, 'collector_service', None)
    if service is None:
        service = Collector(app.data_dir, app.emit_log, app.emit_progress)
        app.collector_service = service
    return service

def note_id(url):
    p=urlparse(url)
    if (p.hostname or '').lower() not in {'www.xiaohongshu.com','xiaohongshu.com'}:
        return None
    m=re.search(r'/(?:explore|discovery/item|search_result)/([0-9a-f]{24})(?:/|$)',p.path)
    return m.group(1) if m else None

def normalized_tag(value):
    value=unicodedata.normalize('NFKC',str(value)).strip()
    value=re.sub(r'\[话题\]|[＃#\s]','',value)
    return value.casefold()

def requested_topics(value):
    return list(dict.fromkeys(normalized_tag(s) for s in re.split(r'[,，;；\s#＃]+',value) if normalized_tag(s)))

def matches_topics(note,topics):
    tags={normalized_tag(t.get('name','')) for t in note.get('tagList',note.get('tag_list',[])) if isinstance(t,dict)}
    return all(t in tags for t in topics)

def find_note(html,identifier):
    for state in states(html):
        for n in walk(state):
            if str(n.get('noteId') or n.get('note_id') or '')==identifier and ('imageList' in n or 'video' in n):
                return n
    return None

def canonical_url(identifier,url='',token=''):
    if not re.fullmatch(r'[0-9a-f]{24}',identifier):raise ValueError('作品编号无效')
    params=parse_qs(urlparse(url).query)
    token=token or (params.get('xsec_token') or [''])[0]
    query={'xsec_source':(params.get('xsec_source') or ['pc_search'])[0]}
    if token:query['xsec_token']=token
    return 'https://www.xiaohongshu.com/explore/'+identifier+'?'+urlencode(query)

@dataclass
class Candidate:
    identifier:str
    url:str
    title:str
    author:str=''
    likes:str=''
    kind:str='图片'
    thumbnail:str=''
    thumbnail_bytes:bytes=field(default=b'',repr=False)

class History:
    """Only completed notes are global duplicates. No credentials go into this DB."""
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS completed (note_id TEXT PRIMARY KEY,title TEXT NOT NULL,mode TEXT NOT NULL,files TEXT NOT NULL,saved_at REAL NOT NULL)')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(str(self.path),timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()
    def contains(self,identifier):
        with self.connect() as db:
            row=db.execute('SELECT files FROM completed WHERE note_id=?',(identifier,)).fetchone()
        return row is not None and saved_files_exist(row[0])
    def count(self):
        with self.connect() as db:return db.execute('SELECT COUNT(*) FROM completed').fetchone()[0]
    def mark(self,candidate,mode,files):
        with self.connect() as db:
            db.execute('INSERT INTO completed VALUES(?,?,?,?,?) ON CONFLICT(note_id) DO UPDATE SET '
                       'title=excluded.title,mode=excluded.mode,files=excluded.files,saved_at=excluded.saved_at',
                       (candidate.identifier,candidate.title,mode,json.dumps([str(Path(p).resolve()) for p in files],ensure_ascii=False),time.time()))

def selected_assets(work,mode):
    kinds={'图片':{'image'},'视频':{'video'},'全部':{'image','video'}}
    if mode not in kinds:raise ValueError('素材类型无效')
    if kinds[mode].intersection(work.missing_kinds):
        raise SourceUnavailable('作品有实况视频未返回可用原始地址，未作为完整作品保存。可切换“图片”只保存照片。')
    assets=[a for a in work.assets if a.kind in kinds[mode]]
    if not assets:raise SourceUnavailable('此作品没有所选类型的可下载素材。')
    return assets

def save_work(work,candidate,folder,mode,downloader,history,cancel):
    """Stage all selected media before committing a completed-note record."""
    if history.contains(candidate.identifier):return []
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    assets=selected_assets(work,mode)
    committed=[]
    try:
        with tempfile.TemporaryDirectory(prefix='.qingying-collection-',dir=folder) as temp:
            downloader.log(f'作品 {candidate.identifier}：并发保存 {len(assets)} 个文件')
            pending,errors=downloader.fetch_many(assets,Path(temp),f'{work.title[:40]}_{candidate.identifier}',work.referer)
            if errors:raise ValueError('作品未完整保存：'+'；'.join(errors))
            check_cancel(cancel)
            for p in pending:
                target=folder/p.name
                if target.exists():target=unique_path(folder,p.stem,p.suffix)
                p.rename(target);committed.append(target)
            # There is no completion record for skipped, failed, or cancelled work.
            history.mark(candidate,mode,committed)
        return committed
    except BaseException:
        for p in committed:
            if p.parent==folder and p.is_file():p.unlink()
        raise

class BrowserWorker:
    """All Playwright calls live on one thread, including login-session reuse."""
    def __init__(self,data_dir,log,embedded=False):
        self.data_dir=Path(data_dir);self.log=log
        self.embedded=None
        if embedded:
            from facebook_browser import EmbeddedFacebook
            self.embedded=EmbeddedFacebook(self.data_dir/'embedded',site=embedded if isinstance(embedded,str) else 'collector')
        self.jobs=queue.Queue();self.context=None;self.page=None;self.detail=None;self.browser=None
        self.search_cache={};self.feed_notes={};self.signature=None;self.resolved={}
        self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()
    def call(self,operation,*args):
        future=Future();self.jobs.put((operation,args,future));return future.result()
    def shutdown(self):self.jobs.put(None)
    def _run(self):
        self.playwright=None
        try:
            while True:
                try:job=self.jobs.get(timeout=.15)
                except queue.Empty:
                    if self.context:
                        try:self.context.pages[0].wait_for_timeout(25)
                        except Exception:pass
                    continue
                if job is None:break
                op,args,future=job
                try:future.set_result(getattr(self,'_'+op)(*args))
                except Exception as e:future.set_exception(e)
        finally:
            # The attached Edge and all of its tabs belong to the user.
            # Stop only our Playwright connection; never close that context.
            if self.playwright:
                try:self.playwright.stop()
                except Exception:pass
            if self.embedded:self.embedded.shutdown()
    def _ensure(self):
        if self.context:
            try:
                if self.context.pages and not self.page.is_closed():return
            except Exception:pass
            self.context=None
        if not self.playwright:
            from playwright.sync_api import sync_playwright
            self.playwright=sync_playwright().start()
        if self.embedded:
            endpoint=self.embedded.call('endpoint')
            self.browser=self.playwright.chromium.connect_over_cdp(endpoint,timeout=20000)
            if not self.browser.contexts:
                raise ValueError('清影内置浏览器尚未就绪，请稍后重试。')
            self.context=self.browser.contexts[0]
            self.page=self.context.pages[0] if self.context.pages else self.context.wait_for_event('page',timeout=15000)
            self.log('已连接清影内置浏览器，将在窗口内自动操作。')
        else:
            from edge_browser import connect
            self.browser,self.context=connect(self.playwright)
            self.page=self.context.new_page()
        self.detail=None;self.signature=None;self.search_cache={};self.feed_notes={};self.resolved={}
        self.search_serial=0;self.last_search_options={}
        self.page.on('popup',lambda page:page.on('response',self._response))
        self.page.on('response',self._response)
        self.page.set_default_timeout(6000)
    def _response(self,response):
        if 'xiaohongshu.com/api/' not in response.url or not any(s in response.url for s in ('search/notes','/feed')):return
        try:
            data=response.json().get('data') or {}
            if 'search/notes' in response.url:
                self.search_serial+=1
                options=response.request.post_data_json or {}
                self.last_search_options={k:options.get(k) for k in ('keyword','sort','note_type','filters') if k in options}
            for item in data.get('items') or []:
                card=item.get('note_card') or item.get('noteCard') or {}
                identifier=str(item.get('id') or card.get('note_id') or card.get('noteId') or '')
                if not re.fullmatch(r'[0-9a-f]{24}',identifier):continue
                if '/feed' in response.url:
                    self.feed_notes[identifier]=card
                    continue
                cover=card.get('cover') or {};user=card.get('user') or {};interact=card.get('interact_info') or {}
                self.search_cache[identifier]=Candidate(identifier,canonical_url(identifier,token=item.get('xsec_token') or card.get('xsec_token') or ''),
                    card.get('display_title') or card.get('title') or identifier,user.get('nickname') or user.get('nick_name') or '',
                    str(interact.get('liked_count') or ''),'视频' if card.get('type')=='video' else '图片',
                    cover.get('url_default') or cover.get('url') or cover.get('url_pre') or '')
        except Exception:pass
    def _login(self):
        self._ensure()
        if self.page.url=='about:blank':self.page.goto('https://www.xiaohongshu.com/',wait_until='domcontentloaded',timeout=30000)
        self.page.bring_to_front()
        if self.embedded:
            self.embedded.call('show')
            return '已打开小红书内置浏览器；请手动登录或完成验证，然后回清影点击搜索。登录状态会保留。'
        return '已连接桌面 Edge。使用你平时的登录状态；需要时请在 Edge 手动登录，完成后回清影搜索。'
    def _gated(self,page):
        try:text=page.locator('body').inner_text(timeout=3000)
        except Exception:return False
        if any(s in text for s in ('安全验证','请完成验证','验证后继续')):
            raise LoginRequired('小红书要求安全验证。请在浏览器窗口手动完成，再回清影继续搜索。')
        if ('/login' in page.url or '登录后查看搜索结果' in text or '登录后查看笔记' in text
                or '登录后推荐更懂你的笔记' in text):
            page.bring_to_front()
            raise LoginRequired('搜索需要登录。请先在浏览器窗口扫码或手动登录，再回清影点击搜索；登录状态会自动保留。')
        return False
    def _open_note(self,url):
        self._ensure()
        if not note_id(url):raise ValueError('作品链接无效')
        self._detail_page().goto(url,wait_until='domcontentloaded',timeout=30000)
        self.detail.bring_to_front()
        return '已在桌面 Edge打开作品，返回清影后可勾选下载。'
    def _detail_page(self):
        if self.detail is None or self.detail.is_closed():
            if self.embedded:
                previous=set(self.context.pages)
                self.embedded.call('detail')
                for _ in range(50):
                    self.page.wait_for_timeout(100)
                    created=[p for p in self.context.pages if p not in previous]
                    if created:
                        self.detail=created[-1];break
                else:raise ValueError('内置作品详情窗口未能连接，请重试。')
            else:self.detail=self.context.new_page()
            self.detail.set_default_timeout(6000);self.detail.on('response',self._response)
        return self.detail
    def _resolve(self,url,cancel,deadline=None):
        self._ensure();check_cancel(cancel)
        parsed=urlparse(url)
        short_link=parsed.scheme=='https' and parsed.hostname in {'xhslink.com','www.xhslink.com'}
        identifier=note_id(url)
        if not identifier and not short_link:raise ValueError('作品链接无效')
        cached=self.resolved.get(identifier)
        if cached and time.monotonic()-cached[0]<120:
            return cached[1],cached[2],self.context.cookies(['https://www.xiaohongshu.com/'])
        detail=self._detail_page()
        timeout=30000 if deadline is None else max(1,min(12000,int((deadline-time.monotonic())*1000)))
        detail.goto(url,wait_until='domcontentloaded',timeout=timeout)
        if short_link:
            check_cancel(cancel)
            self._gated(detail)
            url=detail.url
            identifier=note_id(url)
            if not identifier:raise SourceUnavailable('小红书短链接未跳转到作品，请重新复制完整分享链接。')
        note=None;html=''
        for _ in range(8):
            check_cancel(cancel)
            if deadline is not None and time.monotonic()>=deadline:
                raise SourceUnavailable('本批搜索核对已达到时间上限。')
            self._gated(detail)
            html=detail.content();note=find_note(html,identifier) or self.feed_notes.get(identifier)
            if note and ('imageList' in note or 'image_list' in note or 'video' in note):break
            detail.wait_for_timeout(400)
        if not note:raise SourceUnavailable('作品详情未返回可用数据，未作为成功采集。请在浏览器检查作品是否可访问。')
        if 'image_list' in note and 'imageList' not in note:note=dict(note,imageList=note['image_list'])
        if 'noteId' not in note:note=dict(note,noteId=identifier)
        serialized='<script>window.__INITIAL_STATE__='+json.dumps({'note':{'noteDetailMap':{identifier:{'note':note}}}},ensure_ascii=False)+'</script>'
        work=parse_xhs(serialized,identifier,url)
        if len(self.resolved)>=100:self.resolved.pop(next(iter(self.resolved)))
        self.resolved[identifier]=(time.monotonic(),work,note)
        cookies=self.context.cookies(['https://www.xiaohongshu.com/'])
        return work,note,cookies
    def _dom_cards(self):
        return self.page.locator('section.note-item').evaluate_all('''els=>els.map(el=>{
            const a=el.querySelector('a.cover,a[href*="/search_result/"],a[href*="/explore/"]');
            const im=el.querySelector('img');
            return {url:a?.href||'',title:el.querySelector('.title')?.innerText||'',author:el.querySelector('.author')?.innerText||'',
              likes:el.querySelector('.like-wrapper')?.innerText||'',thumbnail:im?.currentSrc||im?.src||'',
              kind:el.querySelector('.play-icon,.video-icon')?'视频':'图片'};})''')
    def _wait_results(self,cancel,since=None):
        for _ in range(75):
            check_cancel(cancel);self._gated(self.page)
            visible_ids={note_id(raw['url']) for raw in self._dom_cards()}
            if '/search_result' in urlparse(self.page.url).path and visible_ids.intersection(self.search_cache) and (since is None or self.search_serial>since):
                self.page.wait_for_timeout(250);return
            self.page.wait_for_timeout(400)
        raise SourceUnavailable('小红书搜索结果未完成加载，请在浏览器窗口检查登录或验证后重试。')
    def _start_search(self,query,cancel):
        self.page.goto('https://www.xiaohongshu.com/',wait_until='domcontentloaded',timeout=30000)
        self._gated(self.page)
        previous=set(self.context.pages);before=self.search_serial
        self.page.locator('#search-input').fill(query)
        self.page.locator('#search-input').press('Enter')
        self.page.wait_for_timeout(500)
        new_pages=[p for p in self.context.pages if p not in previous]
        if new_pages:self.page=new_pages[-1]
        if '/search_result' not in urlparse(self.page.url).path:
            # The SSR input can appear before its Enter handler is hydrated.
            check_cancel(cancel)
            self.page.goto('https://www.xiaohongshu.com/search_result?'+urlencode({'keyword':query,'source':'web_explore_feed'}),
                           wait_until='domcontentloaded',timeout=15000)
        self._wait_results(cancel,before)
    def _apply_filters(self,mode,sort,cancel):
        if mode in ('图片','视频'):
            tab='图文' if mode=='图片' else '视频'
            self.search_cache={}
            before=self.search_serial
            self.page.get_by_text(tab,exact=True).first.click(timeout=5000)
            self._wait_results(cancel,before)
        if sort!='综合':
            try:
                self.page.get_by_text('筛选',exact=True).first.hover(timeout=4000)
                self.search_cache={}
                before=self.search_serial
                self.page.get_by_text(sort,exact=True).last.click(timeout=4000)
                self.page.mouse.move(30,100)
                self._wait_results(cancel,before)
            except Exception as e:
                raise ValueError('未能在小红书页面应用所选排序，未返回其他排序冒充结果。请在浏览器确认筛选栏后重试。') from e
    def _search(self,keyword,topic,mode,sort,excluded,history_path,cancel,on_update=None):
        result=[];seen=set(excluded)
        counts={'read':0,'reason':''}
        def publish(searching=True):
            counts['searching']=searching
            if on_update:on_update(list(result),dict(counts))
        try:
            publish()
            self._ensure();check_cancel(cancel)
            query=' '.join(value.strip() for value in (keyword,topic) if value.strip())
            if not query:raise ValueError('请输入关键词。')
            signature=(keyword.strip(),topic.strip(),mode,sort)
            if signature!=self.signature:
                self.signature=None;self.search_cache={}
                self._start_search(query,cancel)
                self._apply_filters(mode,sort,cancel)
                self.signature=signature
            deadline=time.monotonic()+20
            for _ in range(8):
                check_cancel(cancel);self._gated(self.page)
                for raw in self._dom_cards():
                    check_cancel(cancel)
                    identifier=note_id(raw['url'])
                    # Preserve webpage order and exclude recommendation cards.
                    if identifier not in self.search_cache or identifier in seen:continue
                    seen.add(identifier);counts['read']+=1
                    item=self.search_cache[identifier]
                    if not item.thumbnail:item.thumbnail=raw.get('thumbnail','')
                    result.append(item);publish()
                    if len(result)==5:return result,counts
                if time.monotonic()>=deadline:break
                self.page.mouse.wheel(0,1000);self.page.wait_for_timeout(600)
            counts['reason']=f'网页当前返回 {len(result)} 个新结果，可点击“换一批”继续。'
            return result,counts
        except Exception as error:
            counts['reason']=str(error).splitlines()[0]
            raise
        finally:
            publish(False)

def download_cover(url):
    """Fetch a bounded public CDN cover without resolving the note."""
    if url.startswith('//'):url='https:'+url
    parsed=urlparse(url);host=(parsed.hostname or '').lower()
    if parsed.scheme not in ('http','https') or not any(host==domain or host.endswith('.'+domain) for domain in ('xhscdn.com','xhsimg.com','xiaohongshu.com')):return b''
    if parsed.scheme=='http':url='https:'+url[5:]
    from core import DESKTOP_UA
    from network_config import desktop_proxies
    with requests.Session() as session:
        session.proxies.update(desktop_proxies());session.trust_env=False
        with session.get(url,headers={'Referer':'https://www.xiaohongshu.com/','User-Agent':DESKTOP_UA},
                         stream=True,timeout=(3,3),allow_redirects=False) as response:
            response.raise_for_status()
            if not response.headers.get('Content-Type','').lower().startswith('image/'):return b''
            chunks=[];size=0;deadline=time.monotonic()+6
            for block in response.iter_content(64*1024):
                size+=len(block)
                if size>2_000_000 or time.monotonic()>deadline:return b''
                chunks.append(block)
            return b''.join(chunks)


class Collector:
    def __init__(self,data_dir,log,progress):
        self.data_dir=Path(data_dir);self.log=log;self.progress=progress
        self.history=History(self.data_dir/'history.sqlite3')
        self.browser=BrowserWorker(self.data_dir,log,embedded=True)
    def search(self,keyword,topic,mode,sort,excluded,cancel,on_update=None):
        return self.browser.call('search',keyword,topic,mode,sort,set(excluded),self.history.path,cancel,on_update)
    def load_thumbnails(self,items,on_thumbnail):
        def fetch(item):
            try:
                data=download_cover(item.thumbnail)
                if data:on_thumbnail(item.identifier,data)
            except Exception:
                self.log('作品封面暂时加载失败，可继续查看或下载作品。')
        for item in items[:5]:
            if item.thumbnail and not item.thumbnail_bytes:
                threading.Thread(target=fetch,args=(item,),daemon=True,name='qingying-cover').start()
    def login(self):return self.browser.call('login')
    def open_note(self,url):return self.browser.call('open_note',url)
    def close(self):self.browser.shutdown()
    def download(self,candidates,folder,mode,mute,cancel):
        saved=[];failures=[];skipped=0
        for i,c in enumerate(candidates,1):
            check_cancel(cancel)
            if self.history.contains(c.identifier):
                skipped+=1;self.log('跳过已采集作品：'+c.title[:40]);continue
            self.log(f'下载作品 {i}/{len(candidates)}：{c.title[:45]}')
            d=Downloader(cancel,self.log,self.progress,mute=mute)
            try:
                work,_,cookies=self.browser.call('resolve',c.url,cancel)
                for cookie in cookies:
                    d.session.cookies.set(cookie['name'],cookie['value'],domain=cookie.get('domain',''),path=cookie.get('path','/'),secure=cookie.get('secure',False))
                files=save_work(work,c,folder,mode,d,self.history,cancel)
                if files:saved.append((c,files));self.log(f'作品完整保存成功：{len(files)} 个文件；已写入去重记录。')
            except (LoginRequired,Cancelled):raise
            except Exception as e:
                failures.append((c.identifier,str(e)));self.log('作品未完成，不写入去重：'+str(e).splitlines()[0][:180])
            finally:d.session.close()
        return saved,failures,skipped

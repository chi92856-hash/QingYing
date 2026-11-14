"""Local glass presentation, reusing the existing Tk-owned application actions.

Only the bundled local HTML receives this API. The Facebook login browser
remains an independent process with no Python API exposed to its web pages.
"""
import base64
import io
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
from multiprocessing.connection import Client, Listener
from pathlib import Path
from common import LocalRPC, save_settings


class GlassHost:
    def __init__(self, app, initial='download'):
        self.app = app
        self.page = initial
        self.requests = queue.Queue()
        self.connection = None
        self.stopped = False
        self.image_key = None
        self.image_data = None
        self.thumbnails = {}
        key = secrets.token_bytes(32)
        family = 'AF_PIPE' if os.name == 'nt' else 'AF_INET'
        address = r'\\.\pipe\qingying-' + secrets.token_hex(16) if os.name == 'nt' else ('127.0.0.1', 0)
        self.listener = Listener(address, family=family, authkey=key)
        env = os.environ.copy()
        env['QINGYING_GLASS'] = json.dumps({'address': self.listener.address, 'family': family, 'key': key.hex()})
        entry = Path(__file__).with_name('app.py')
        command = [sys.executable, '--glass-window'] if getattr(sys, 'frozen', False) else [sys.executable, str(entry), '--glass-window']
        self.process = subprocess.Popen(command, env=env, creationflags=0x08000000 if os.name == 'nt' else 0)
        threading.Thread(target=self.serve, daemon=True).start()
        app.after(40, self.pump)
        app.after(15000, self.check_started)

    def check_started(self):
        if self.connection is None and not self.stopped:
            self.app.deiconify()
            self.app.status.set('玻璃界面未能启动，已打开兼容界面。')

    def serve(self):
        try:
            self.connection = self.listener.accept()
            self.listener.close()
            while not self.stopped:
                operation, data = self.connection.recv()
                answer = queue.Queue(maxsize=1)
                self.requests.put((operation, data, answer))
                result = answer.get()
                self.connection.send(result)
        except (EOFError, OSError, BrokenPipeError):
            if not self.stopped:
                self.requests.put(('close', {}, queue.Queue(maxsize=1)))

    def pump(self):
        if self.stopped:
            return
        for _ in range(12):
            try:
                operation, data, answer = self.requests.get_nowait()
            except queue.Empty:
                break
            try:
                self.dispatch(operation, data or {})
                result = {'state': self.snapshot()} if operation != 'close' else {'closed': True}
            except Exception as error:
                result = {'error': str(error)}
            answer.put(result)
            if operation == 'close':
                return
        self.app.after(40, self.pump)

    def panel(self, page):
        self.app.show_page(page)
        self.page = page

    def apply_form(self, data):
        a = self.app
        if a.busy:
            return
        for key, variable in [('folder', a.folder), ('mute', a.mute)]:
            if key in data:
                variable.set(data[key])
        if 'links' in data:
            a.links.delete('1.0', 'end')
            a.links.insert('1.0', str(data['links']))
        if a.facebook_panel:
            p = a.facebook_panel
            for key, variable in [('profile', p.url), ('fbfolder', p.destination), ('limit', p.item_limit)]:
                if key in data:
                    variable.set(str(data[key]))
            for key, value in data.get('types', {}).items():
                if key in p.types:
                    p.types[key].set(bool(value))
        if getattr(a, 'x_panel', None):
            p = a.x_panel
            if 'xurl' in data:
                p.url.set(str(data['xurl']))
            if data.get('xsource') in ('主页图片', '评论图片'):
                p.source.set(data['xsource'])
            if 'xselected' in data:
                chosen = set(data['xselected'])
                for key, variable in p.selected.items():
                    variable.set(key in chosen)
                p._selection()
        if a.collector_panel:
            p = a.collector_panel
            for key, variable in [('keyword', p.keyword), ('topic', p.topic), ('mode', p.mode), ('sort', p.sort)]:
                if key in data:
                    variable.set(str(data[key]))
            if 'selected' in data:
                wanted = set(data['selected'])
                for identifier, variable in p.selected.items():
                    variable.set(identifier in wanted)

    def persist(self):
        from app import CONFIG
        a = self.app
        options = {'folder': a.folder.get(), 'mute': a.mute.get()}
        if a.facebook_panel:
            options.update(a.facebook_panel.settings())
        if a.collector_panel:
            options.update(a.collector_panel.settings())
        a.saved_settings.update(options)
        save_settings(CONFIG, a.saved_settings)

    def dispatch(self, operation, data):
        a = self.app
        if operation == 'snapshot':
            return
        if operation == 'navigate':
            if data.get('page') not in ('facebook', 'download', 'collector', 'edit', 'x'):
                raise ValueError('未知工作页。')
            self.apply_form(data)
            self.panel(data['page'])
            return
        if operation == 'classic':
            a.deiconify()
            a.lift()
            return
        if operation == 'updates':
            from updater import check_from_ui
            check_from_ui(a)
            return
        if operation == 'close':
            self.apply_form(data)
            try:
                self.persist()
            except OSError:
                a.add_log('设置未能保存，请检查程序目录是否可写。')
            a.after(100, a.close)
            return
        if operation == 'stop':
            a.stop()
            return
        if a.busy:
            raise ValueError('任务正在进行，请先暂停。')
        self.apply_form(data)
        if operation == 'save':
            self.persist()
        elif operation == 'facebook_start':
            a.facebook_panel.download()
        elif operation == 'facebook_login':
            a.facebook_panel.open_browser()
        elif operation == 'facebook_folder':
            a.facebook_panel.choose_folder()
            self.persist()
        elif operation == 'folder':
            a.select_folder()
            self.persist()
        elif operation == 'open_folder':
            a.open_folder()
        elif operation == 'paste':
            a.paste()
        elif operation == 'download':
            a.start_download()
        elif operation == 'resume':
            a.resume_download()
        elif operation == 'cookie':
            a.select_cookie()
        elif operation == 'cookie_clear':
            a.cookie.set('')
        elif operation == 'instagram':
            a.instagram_login()
        elif operation in ('x_login', 'x_search', 'x_download'):
            panel = getattr(a, 'x_panel', None)
            if panel is None:
                raise ValueError('请先打开 X 图片采集页。')
            {'x_login': panel.login, 'x_search': panel.search, 'x_download': panel.download}[operation]()
        elif operation == 'x_open':
            panel = getattr(a, 'x_panel', None)
            item = next((item for item in panel.items if item.identifier == data.get('id')), None) if panel else None
            if item:
                panel.open_note(item.url)
        elif operation == 'collector_login':
            a.collector_panel.login()
        elif operation in ('collector_search', 'collector_next'):
            a.collector_panel.search(operation == 'collector_next')
        elif operation == 'collector_download':
            a.collector_panel.download()
        elif operation == 'collector_open':
            item = next((item for item in a.collector_panel.items if item.identifier == data.get('id')), None)
            if item:
                a.collector_panel.open_note(item.url)
        elif operation == 'media':
            a.select_media()
        elif operation == 'undo':
            a.undo()
        elif operation == 'clear':
            a.clear()
        elif operation == 'preview':
            a.preview()
        elif operation == 'restore':
            a.start_restore()
        elif operation == 'seek':
            a.video_pos.set(max(0, min(99, float(data.get('position', 0)))))
            a.seek(a.video_pos.get())
        elif operation == 'box':
            if a.original is not None:
                width, height = a.original.size
                x1, y1, x2, y2 = [float(n) for n in data['box']]
                box = (int(max(0, min(x1, x2, width))), int(max(0, min(y1, y2, height))),
                       int(max(0, min(max(x1, x2), width))), int(max(0, min(max(y1, y2), height))))
                if box[2] - box[0] >= 3 and box[3] - box[1] >= 3:
                    a.boxes.append(box)
                    a.show_result = False
                    a.draw()
                    a.status.set(f'已选择 {len(a.boxes)} 个水印区域')
        else:
            raise ValueError('不支持的操作。')

    def snapshot(self):
        a = self.app
        state = {'page': self.page, 'busy': a.busy, 'status': a.status.get(), 'progress': a.progress.get(),
                 'logs': a.logbox.get('1.0', 'end').strip().splitlines()[-80:], 'folder': a.folder.get(),
                 'mute': a.mute.get(), 'cookie': a.cookie.get(), 'links': a.links.get('1.0', 'end').rstrip(),
                 'notice': a.notice.get(), 'pending': len(a.pending_urls)}
        if a.facebook_panel:
            p = a.facebook_panel
            state.update(profile=p.url.get(), fbfolder=p.destination.get(), limit=p.item_limit.get(),
                         types={key: value.get() for key, value in p.types.items()})
        if a.collector_panel:
            p = a.collector_panel
            items = []
            for item in p.items:
                thumbnail = self.thumbnails.get(item.identifier)
                if thumbnail is None and item.thumbnail_bytes:
                    from PIL import Image
                    try:
                        with Image.open(io.BytesIO(item.thumbnail_bytes)) as image:
                            image.thumbnail((160, 160))
                            output = io.BytesIO()
                            image.convert('RGB').save(output, 'JPEG', quality=78)
                            thumbnail = 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode()
                    except Exception:
                        thumbnail = ''
                    self.thumbnails[item.identifier] = thumbnail
                done = p.service is not None and p.service.history.contains(item.identifier)
                items.append({'id': item.identifier, 'title': item.title, 'author': item.author,
                              'kind': item.kind, 'thumbnail': thumbnail or '', 'done': done,
                              'selected': p.selected[item.identifier].get()})
            state.update(keyword=p.keyword.get(), topic=p.topic.get(), mode=p.mode.get(), sort=p.sort.get(),
                         collector_summary=p.summary.get(), items=items)
        if getattr(a, 'x_panel', None):
            p = a.x_panel
            items = []
            for item in p.items:
                thumbnail = ''
                if item.thumbnail_bytes:
                    thumbnail = 'data:image/jpeg;base64,' + base64.b64encode(item.thumbnail_bytes).decode()
                done = p.service is not None and p.service.history.contains(item.identifier)
                items.append({'id': item.identifier, 'title': item.title, 'author': item.author,
                              'thumbnail': thumbnail, 'done': done,
                              'selected': p.selected[item.identifier].get()})
            state.update(xurl=p.url.get(), xsource=p.source.get(), xsummary=p.summary.get(), xitems=items)
        if self.page == 'edit':
            image = getattr(a, 'result_image', None) if a.show_result else a.original
            key = id(image) if image is not None else None
            if key != self.image_key:
                self.image_key = key
                if image is not None:
                    copy = image.copy()
                    copy.thumbnail((1200, 800))
                    output = io.BytesIO()
                    copy.convert('RGB').save(output, 'JPEG', quality=88)
                    self.image_data = 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode()
                else:
                    self.image_data = None
            state.update(image=self.image_data, image_key=key, boxes=a.boxes,
                         dimensions=list(a.original.size) if a.original is not None else None,
                         filename=a.source.name if a.source else '', video=a.duration is not None,
                         position=a.video_pos.get(), show_result=a.show_result)
        return state

    def close(self):
        self.stopped = True
        self.listener.close()
        if self.connection:
            self.connection.close()


def glass_main():
    import webview
    config = json.loads(os.environ.pop('QINGYING_GLASS'))
    address = tuple(config['address']) if config['family'] == 'AF_INET' else config['address']
    connection = Client(address, family=config['family'], authkey=bytes.fromhex(config['key']))
    lock = threading.Lock()
    rpc = LocalRPC(connection, 120, '操作等待超时，请检查是否有文件选择或登录窗口。')

    window_state = {"maximized": False}
    close_state = {"form": {}, "requested": False}

    class API:
        def window_action(self, action, data=None):
            if action == "minimize":
                window.minimize()
            elif action == "maximize":
                if window_state["maximized"]:
                    window.restore()
                else:
                    window.maximize()
            elif action == "close":
                close_state["form"] = data or {}
                window.destroy()
            else:
                raise ValueError("未知窗口操作。")
            return dict(window_state)

        def dispatch(self, operation, data=None):
            if data:
                close_state["form"] = data
            with lock:
                try:
                    return rpc.request((operation, data or {}))
                except TimeoutError as error:
                    return {'error': str(error)}
                except (EOFError, OSError):
                    return {'closed': True}

    api = API()
    html = Path(__file__).with_name('glass_ui.html').read_text(encoding='utf-8')
    from updater import VERSION
    window = webview.create_window(f'清影 v{VERSION} · 素材工作台', html=html, js_api=api,
                                   width=1280, height=920, min_size=(1000, 720), background_color='#080809',
                                   frameless=True, easy_drag=False, shadow=True)

    def closing():
        # Native closing runs on the UI thread: evaluating JS here would deadlock.
        if not close_state['requested']:
            close_state['requested'] = True
            api.dispatch('close', close_state['form'])
        return True

    window.events.maximized += lambda: window_state.update(maximized=True)
    window.events.restored += lambda: window_state.update(maximized=False)
    window.events.closing += closing
    webview.start(gui='edgechromium', private_mode=True)
    connection.close()

"""Run the offline regressions against code extracted from the candidate EXE."""
import marshal
from pathlib import Path
import struct
import sys
import types
import zlib
from update_bundle import read_archive, ROOT

bundle = ROOT / '清影' / '清影-一体窗口.exe'
if not bundle.exists():
    bundle = ROOT / '清影' / '清影.exe'
_, entries, _ = read_archive(bundle.read_bytes())
payload = next(block for name, _, _, _, block in entries if name == 'PYZ.pyz')
toc = dict(marshal.loads(payload[struct.unpack('!i', payload[8:12])[0]:]))


def load(name):
    _, position, length = toc[name]
    code = marshal.loads(zlib.decompress(payload[position:position + length]))
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / '清影' / '_internal' / (name + '.pyc'))
    sys.modules[name] = module
    exec(code, module.__dict__)
    return module


common = load('common')
core = load('core')
facebook = load('facebook_history')
collector = load('collector')
browser = load('facebook_browser')
assert browser.LocalRPC is common.LocalRPC
import regression_checks
assert regression_checks.LocalRPC is common.LocalRPC
assert regression_checks.FacebookHistory is facebook.FacebookHistory
regression_checks.collector_history_class = lambda: collector.History
regression_checks.main()
print('PASS: regressions used candidate EXE modules, including full collector imports')

instagram = load('instagram_support')
import download_regression_checks
assert download_regression_checks.instagram is instagram
app_entry = next((flag, block) for name, _, flag, _, block in entries if name == 'app')
app_code = marshal.loads(zlib.decompress(app_entry[1]) if app_entry[0] else app_entry[1])
app_code = marshal.loads(next(c for c in app_code.co_consts if isinstance(c, bytes)))
app_class = next(c for c in app_code.co_consts if isinstance(c, types.CodeType) and c.co_name == 'App')
start_method = next(c for c in app_class.co_consts if isinstance(c, types.CodeType) and c.co_name == 'start_download')
download_regression_checks.check_downloads(start_method)
download_regression_checks.check_updates()
print('PASS: cookie/cancellation checks used the packaged app entrypoint and Instagram module')

import embedded_browser_checks
embedded_browser_checks.check_browser(collector.BrowserWorker)

import search_progress_checks
search_progress_checks.check_search(collector.BrowserWorker)
_,position,length=toc['collector_ui']
ui_code=marshal.loads(zlib.decompress(payload[position:position+length]))
panel_class=next(c for c in ui_code.co_consts if isinstance(c,types.CodeType) and c.co_name=='CollectorPanel')
handle_batch=next(c for c in panel_class.co_consts if isinstance(c,types.CodeType) and c.co_name=='handle_batch')
search_progress_checks.check_panel(handle_batch)

import thumbnail_checks
thumbnail_method=next(c for c in panel_class.co_consts if isinstance(c,types.CodeType) and c.co_name=='handle_thumbnail')
thumbnail_checks.check_thumbnails(collector.download_cover,thumbnail_method)

x_support = load('x_support')
x_ui = load('x_ui')
import x_checks
assert x_checks.XBrowser is x_support.XBrowser
x_checks.main()
import x_timeline_checks
x_timeline_checks.check()
print('PASS: X media and reply checks used installed EXE modules; X selection UI imports')
import x_sidebar_checks
x_sidebar_checks.check(next(c for c in app_class.co_consts if isinstance(c, types.CodeType) and c.co_name=='show_page'))


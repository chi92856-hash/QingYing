"""Offline checks for the redesigned workbench's added X bridge."""
from types import SimpleNamespace
from glass_host import GlassHost


class Variable:
    def __init__(self, value=None): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


def main():
    calls = []
    panel = SimpleNamespace(url=Variable(''), source=Variable('主页图片'),
                            selected={'one': Variable(False), 'two': Variable(False)},
                            _selection=lambda: calls.append('selection'),
                            login=lambda: calls.append('login'),
                            search=lambda: calls.append('search'),
                            download=lambda: calls.append('download'))
    app = SimpleNamespace(busy=False, folder=Variable('saved'), mute=Variable(False),
                          facebook_panel=None, collector_panel=None, x_panel=panel)
    host = GlassHost.__new__(GlassHost)
    host.app = app
    form = {'xurl': 'https://x.com/example', 'xsource': '评论图片', 'xselected': ['two']}
    host.apply_form(form)
    assert panel.url.get() == form['xurl'] and panel.source.get() == '评论图片'
    assert not panel.selected['one'].get() and panel.selected['two'].get()
    host.dispatch('x_search', form)
    host.dispatch('x_download', form)
    host.dispatch('x_login', form)
    assert calls[-1] == 'login' and 'search' in calls and 'download' in calls
    app.busy = True
    host.apply_form({'xurl': 'must not change', 'xselected': []})
    assert panel.url.get() == form['xurl'] and panel.selected['two'].get()
    try: host.dispatch('x_download', {})
    except ValueError: pass
    else: raise AssertionError('Busy workbench allowed a second download')
    print('PASS: X form, explicit selection, login/search/download routing and busy guard')


if __name__ == '__main__': main()

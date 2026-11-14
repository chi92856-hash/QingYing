"""Verify X page routing without capturing or driving the desktop."""
import types
from pathlib import Path
from unittest.mock import Mock, patch


def check(method):
    app = types.SimpleNamespace(
        pages={key: Mock() for key in ('download', 'edit', 'collector', 'facebook', 'x')},
        busy=False, collector_panel=Mock(), facebook_panel=Mock(), output_panel=Mock(),
        page_title=Mock(), page_subtitle=Mock(), stop_btn=Mock(),
        **{'nav_'+key: Mock() for key in ('download','edit','collector','facebook','x')})
    show = types.FunctionType(method, {'APP_DIR':Path('.'), 'build_editor':Mock()})
    with patch('x_ui.XPanel') as panel, patch('mac_theme.icon', return_value=None):
        show(app, 'x')
        panel.assert_called_once_with(app.pages['x'], app, Path('x_data'))
        app.pages['x'].tkraise.assert_called_once()
        app.page_title.configure.assert_called_with(text='X 图片获取')
        assert app.nav_x.configure.call_args.kwargs['fg_color'] == '#D9E9FF'
        show(app, 'download')
        show(app, 'x')
        assert panel.call_count == 1, 'Navigation must preserve existing results and selections'
        app.output_panel.grid.assert_called()
    print('PASS: X sidebar routing, active state, shared output folder and preserved panel')

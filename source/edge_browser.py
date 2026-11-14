"""Attach to the user's normal Edge after its own connection permission."""
import os,re,subprocess
from pathlib import Path

class EdgeConnectionRequired(ValueError):pass

HELP='尚未连接桌面 Edge。请在平时使用的 Edge 打开 edge://inspect/#remote-debugging，手动勾选“允许对此浏览器实例进行远程调试”，再回清影重试；如 Edge 弹出连接确认，请手动允许。'

def debug_endpoint(root=None):
    root=Path(root) if root else Path(os.environ['LOCALAPPDATA'])/'Microsoft/Edge/User Data'
    try:
        lines=(root/'DevToolsActivePort').read_text('utf-8').splitlines()
        port=int(lines[0]);path=lines[1]
        if not 1<=port<=65535 or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9._-]+',path):raise ValueError()
        return f'ws://127.0.0.1:{port}{path}'
    except (OSError,ValueError,IndexError):raise EdgeConnectionRequired(HELP) from None

def open_desktop_edge(url):
    if url!='edge://inspect/#remote-debugging' and url not in ('https://www.instagram.com/','https://www.xiaohongshu.com/'):
        raise ValueError('浏览器入口地址无效')
    candidates=[Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',
                Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Microsoft/Edge/Application/msedge.exe']
    executable=next((p for p in candidates if p.is_file()),None)
    if not executable:raise EdgeConnectionRequired('未找到桌面 Microsoft Edge，请先确认 Edge 已安装。')
    # No separate user-data directory, new profile, proxy or security flags.
    subprocess.Popen([str(executable),'--new-tab',url],creationflags=0x08000000 if os.name=='nt' else 0)

def connect(playwright):
    try:endpoint=debug_endpoint()
    except EdgeConnectionRequired:
        open_desktop_edge('edge://inspect/#remote-debugging')
        raise
    try:
        browser=playwright.chromium.connect_over_cdp(endpoint,timeout=12000)
        if not browser.contexts:raise ValueError('Edge 未返回当前会话')
        return browser,browser.contexts[0]
    except Exception:
        raise EdgeConnectionRequired('无法连接已授权的桌面 Edge。请确认 Edge 仍打开，并在远程调试页面允许当前连接后重试。') from None

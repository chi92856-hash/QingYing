"""Check the project's GitHub Releases and stage verified executable updates."""
import hashlib
import re
import sys
import tempfile
from pathlib import Path

import requests
from core import check_cancel
from network_config import desktop_proxies


VERSION = '1.7.2'
REPOSITORY = 'chi92856-hash/qingying'
RELEASES = f'https://github.com/{REPOSITORY}/releases'
ASSET_NAME = 'Qingying.exe'
MAX_BYTES = 128 * 1024 * 1024


def session():
    client = requests.Session()
    client.trust_env = False
    client.proxies.update(desktop_proxies())
    return client


def check_latest():
    with session() as client:
        response = client.get(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',
                              headers={'Accept': 'application/vnd.github+json'}, timeout=(5, 12))
        if response.status_code == 404:
            raise ValueError('GitHub 未返回可公开读取的正式版本。请检查仓库权限及 Releases 是否已发布。')
        response.raise_for_status()
        release = response.json()
    tag = release.get('tag_name', '')
    match = re.fullmatch(r'v?(\d{1,6})\.(\d{1,6})\.(\d{1,6})', tag)
    if not match:
        raise ValueError('GitHub 正式版本的标签应为 v主版本.次版本.修订版本。')
    if tuple(map(int, match.groups())) <= tuple(map(int, VERSION.split('.'))):
        return None
    for asset in release.get('assets', ()):
        if asset.get('name') != ASSET_NAME or asset.get('state') != 'uploaded':
            continue
        size, digest = asset.get('size'), asset.get('digest') or ''
        if type(size) is int and 0 < size <= MAX_BYTES and re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            return tag, size, digest[7:]
    raise ValueError(f'发现 {tag}，但 GitHub Release 缺少可校验的 {ASSET_NAME}。')


def download(offer, cancel, progress):
    tag, size, expected = offer
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
    folder = base / 'updates' / tag
    folder.mkdir(parents=True, exist_ok=True)
    url = f'{RELEASES}/download/{tag}/{ASSET_NAME}'
    digest = hashlib.sha256()
    received = 0
    with tempfile.TemporaryDirectory(dir=folder) as temporary:
        candidate = Path(temporary) / ASSET_NAME
        with session() as client, client.get(url, stream=True, timeout=(8, 15)) as response:
            response.raise_for_status()
            with candidate.open('wb') as output:
                for chunk in response.iter_content(256 * 1024):
                    check_cancel(cancel)
                    received += len(chunk)
                    if received > size:
                        raise ValueError('更新文件大小与 GitHub 发布记录不符。')
                    digest.update(chunk)
                    output.write(chunk)
                    progress(received / size * 100, f'正在下载更新 {tag}')
        check_cancel(cancel)
        if received != size or digest.hexdigest() != expected:
            raise ValueError('更新文件校验失败，请重试。')
        candidate.replace(folder / '清影.exe')
    return folder


def check_from_ui(app):
    if app.busy or app.closing:
        return
    def job():
        offer = check_latest()
        if offer is None:
            return f'清影 {VERSION} 已是最新版本。'
        app.events.put(('update_offer', offer))
        return f'发现新版本 {offer[0]}。'
    app.run_job(job)


def offer_download(app, offer):
    from tkinter import messagebox

    tag = offer[0]
    if app.busy or app.closing or not messagebox.askyesno(
            '清影更新', f'发现新版本 {tag}。现在下载并校验？\n下载完成后，可退出清影并手动替换程序。', parent=app):
        return
    def job():
        folder = download(offer, app.cancel, app.emit_progress)
        app.events.put(('update_ready', folder))
        return f'{tag} 已下载并校验。退出清影后，用更新文件替换安装目录里的清影.exe。'
    app.run_job(job)
